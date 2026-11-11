import os
import shutil
import subprocess
import json
from pathlib import Path
import torch
import torchaudio
import soundfile as sf
from gradio_client import Client, handle_file

BASE_DIR = Path(__file__).resolve().parent
DIR_VOCES = BASE_DIR / "voces_clonadas"
DIR_VOCES.mkdir(exist_ok=True)

META_VOCES_FILE = DIR_VOCES / "voces_meta.json"

# 1. Parche para compatibilidad PyTorch 2.6+ (permite cargar checkpoints de TTS)
_orig_torch_load = torch.load
def _safe_torch_load(*args, **kwargs):
    kwargs["weights_only"] = False
    return _orig_torch_load(*args, **kwargs)
torch.load = _safe_torch_load

# 2. Parche para torchaudio.load en Windows usando soundfile (elimina dependencia de torchcodec)
def _sf_load(filepath, **kwargs):
    data, sr = sf.read(str(filepath))
    tensor = torch.from_numpy(data).float()
    if tensor.ndim == 1:
        tensor = tensor.unsqueeze(0)
    else:
        tensor = tensor.t()
    return tensor, sr
torchaudio.load = _sf_load

# Cache en memoria del modelo local XTTS-v2
_tts_local_instancia = None


def obtener_motor_local_xtts():
    """
    Carga e inicializa el modelo local XTTS-v2 en CPU una sola vez y lo mantiene en memoria.
    No requiere llamadas externas, ni clave, ni cuotas de red.
    """
    global _tts_local_instancia
    if _tts_local_instancia is None:
        os.environ["COQUI_TOS_AGREED"] = "1"
        from TTS.api import TTS
        print("-> [PC Local] Cargando modelo XTTS-v2 en memoria CPU...")
        _tts_local_instancia = TTS("tts_models/multilingual/multi-dataset/xtts_v2", progress_bar=False, gpu=False)
        print("-> [PC Local] Modelo XTTS-v2 listo para inferencia local.")
    return _tts_local_instancia


def _cargar_meta_voces() -> dict:
    if META_VOCES_FILE.exists():
        try:
            return json.loads(META_VOCES_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _guardar_meta_voces(meta: dict):
    META_VOCES_FILE.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def listar_perfiles_voz() -> list[dict]:
    """
    Devuelve la lista de voces disponibles con ID, Nombre legible y Archivo de audio.
    """
    meta = _cargar_meta_voces()
    archivos_reales = {
        f.name for f in DIR_VOCES.iterdir()
        if f.is_file() and f.suffix.lower() in [".wav", ".mp3", ".ogg", ".m4a"]
        and not f.name.startswith("temp_")
        and not f.name.startswith("test_")
    }

    perfiles = []
    vistos_arch = set()

    # Si existe muestra_cynthia_10s.wav y no tiene nombre, bautizarla como 'Voz de Cynthia'
    if "muestra_cynthia_10s.wav" in archivos_reales and "muestra_cynthia_10s.wav" not in meta:
        meta["muestra_cynthia_10s.wav"] = {"nombre": "Voz de Cynthia", "archivo": "muestra_cynthia_10s.wav"}
        _guardar_meta_voces(meta)

    for arch, info in meta.items():
        if arch in archivos_reales:
            perfiles.append({
                "id": arch,
                "nombre": info.get("nombre", arch),
                "archivo": arch
            })
            vistos_arch.add(arch)

    # Archivos que están en disco pero no en el meta
    for arch in sorted(archivos_reales):
        if arch not in vistos_arch and not arch.startswith("ref_"):
            perfiles.append({
                "id": arch,
                "nombre": Path(arch).stem.replace("_", " "),
                "archivo": arch
            })

    return perfiles


def guardar_muestra_voz(nombre_perfil: str, nombre_archivo: str, contenido_bytes: bytes) -> dict:
    """
    Guarda una muestra de voz con nombre personalizado (ej: 'Voz de Cynthia', 'Voz de Juan').
    """
    nombre_limpio_slug = "".join(c for c in nombre_perfil if c.isalnum() or c in ("-", "_")).strip().lower() or "voz"
    nombre_wav = f"perfil_{nombre_limpio_slug}_10s.wav"
    destino_wav = DIR_VOCES / nombre_wav

    # Guardar temporal
    temp_orig = DIR_VOCES / f"temp_{Path(nombre_archivo).name}"
    temp_orig.write_bytes(contenido_bytes)

    try:
        subprocess.run(
            ["ffmpeg", "-y", "-ss", "00:00:03", "-t", "10", "-i", str(temp_orig),
             "-ar", "24000", "-ac", "1", str(destino_wav)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True
        )
    except Exception:
        shutil.copy(str(temp_orig), str(destino_wav))
    finally:
        temp_orig.unlink(missing_ok=True)

    meta = _cargar_meta_voces()
    meta[nombre_wav] = {
        "nombre": nombre_perfil.strip() or "Mi Voz Clonada",
        "archivo": nombre_wav
    }
    _guardar_meta_voces(meta)

    return {
        "id": nombre_wav,
        "nombre": meta[nombre_wav]["nombre"],
        "archivo": nombre_wav
    }


def eliminar_perfil_voz(archivo: str) -> bool:
    """Elimina un perfil de voz clonado."""
    ruta = DIR_VOCES / Path(archivo).name
    ruta.unlink(missing_ok=True)
    meta = _cargar_meta_voces()
    if Path(archivo).name in meta:
        del meta[Path(archivo).name]
        _guardar_meta_voces(meta)
    return True


def sintetizar_con_voz_clonada(
    texto: str,
    archivo_muestra_audio: str | Path,
    ruta_salida: str | Path,
    idioma: str = "es"
) -> bool:
    """
    Sintetiza texto con voz clonada zero-shot.
    Prioridad 1: Ejecución local en PC con XTTS-v2 (100% gratuita, privada, sin límites de Hugging Face).
    Prioridad 2: Respaldo en la nube (F5-TTS o XTTS-v2 en Hugging Face Spaces).
    """
    ruta_ref = DIR_VOCES / Path(archivo_muestra_audio).name if not Path(archivo_muestra_audio).is_absolute() else Path(archivo_muestra_audio)
    if not ruta_ref.exists():
        perfiles = listar_perfiles_voz()
        if perfiles:
            ruta_ref = DIR_VOCES / perfiles[0]["archivo"]
        else:
            raise FileNotFoundError(f"No se encontró el audio de referencia de voz: {ruta_ref}")

    # Asegurar que la referencia esté en WAV si es posible
    if ruta_ref.suffix.lower() != ".wav":
        wav_opt = ruta_ref.with_suffix(".wav")
        if not wav_opt.exists():
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(ruta_ref), "-ar", "24000", "-ac", "1", "-t", "12", str(wav_opt)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        if wav_opt.exists():
            ruta_ref = wav_opt

    # 1. EJECUCIÓN LOCAL EN PC CON XTTS-v2 (Prioridad principal, sin límite de Hugging Face)
    try:
        print(f"-> [🎙️ XTTS-v2 Local] Sintetizando audio en tu PC (CPU)...")
        # Preprocesar con seseo si el texto contiene z o c suave para neutralizar el acento español peninsular de XTTS
        try:
            from diccionario_fonetico import aplicar_seseo_latino
            texto_para_xtts = aplicar_seseo_latino(texto)
        except Exception:
            texto_para_xtts = texto

        tts = obtener_motor_local_xtts()
        tts.tts_to_file(
            text=texto_para_xtts,
            speaker_wav=str(ruta_ref),
            language=idioma,
            file_path=str(ruta_salida)
        )
        if Path(ruta_salida).exists() and Path(ruta_salida).stat().st_size > 500:
            print(f"-> Audio clonado localmente generado con éxito: {Path(ruta_salida).name}")
            return True
    except Exception as e_local:
        print(f"Aviso: XTTS-v2 local no completó ({e_local}), probando servidores en la nube como respaldo...")

    # 2. Respaldo Nube: F5-TTS en Hugging Face
    try:
        print(f"-> Conectando a clonador F5-TTS en Hugging Face (mrfakename/E2-F5-TTS)...")
        c = Client("mrfakename/E2-F5-TTS")
        res = c.predict(
            ref_audio=handle_file(str(ruta_ref)),
            ref_text="",
            gen_text=texto,
            remove_silence=False,
            api_name="/predict"
        )
        ruta_gen = res if isinstance(res, str) else (res[0] if isinstance(res, (list, tuple)) else None)
        if ruta_gen and os.path.exists(str(ruta_gen)):
            shutil.copy(str(ruta_gen), str(ruta_salida))
            return True
    except Exception as e_f5:
        print(f"Aviso: F5-TTS nube no respondió ({e_f5}), intentando XTTS v2 nube...")

    # 3. Respaldo Nube: XTTS-v2 en Hugging Face
    try:
        print(f"-> Conectando a XTTS-v2 en Hugging Face (hasanbasbunar/Voice-Cloning-XTTS-v2)...")
        c = Client("hasanbasbunar/Voice-Cloning-XTTS-v2")
        res = c.predict(
            text=texto,
            reference_audio_url=None,
            example_audio_name="audio_1.wav",
            language="Spanish",
            temperature=0.75,
            speed=1.0,
            api_name="/voice_clone_synthesis"
        )
        ruta_gen = res if isinstance(res, str) else (res[0] if isinstance(res, (list, tuple)) else None)
        if ruta_gen and os.path.exists(str(ruta_gen)):
            shutil.copy(str(ruta_gen), str(ruta_salida))
            return True
    except Exception as e_xtts:
        print(f"Aviso: XTTS v2 nube tampoco respondió ({e_xtts})")

    raise RuntimeError("No se pudo sintetizar con modelos de clonación (motor local ni servidores de respaldo).")
