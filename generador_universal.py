import re
import sys
import json
import shutil
import asyncio
import subprocess
from pathlib import Path
import edge_tts
from playwright.sync_api import sync_playwright
from estilo_habla import adaptar_texto_a_mi_estilo
from diccionario_fonetico import aplicar_fonetica
from clonador_voz import sintetizar_con_voz_clonada, DIR_VOCES
from procesador_entradas import convertir_ipynb_a_pasos, auto_segmentar_py_sin_etiquetas

try:
    from moviepy import (
        ImageClip, VideoFileClip, AudioFileClip,
        concatenate_videoclips, concatenate_audioclips
    )
except ImportError:
    from moviepy.editor import (
        ImageClip, VideoFileClip, AudioFileClip,
        concatenate_videoclips, concatenate_audioclips
    )

try:
    from moviepy.config import get_setting
    FFMPEG_BINARY = get_setting("FFMPEG_BINARY")
except Exception:
    import imageio_ffmpeg
    FFMPEG_BINARY = imageio_ffmpeg.get_ffmpeg_exe()


class GeneradorVideoUniversal:
    def __init__(self, ruta_clase: Path):
        self.ruta_clase = ruta_clase.resolve()
        self.base_dir = Path(__file__).resolve().parent
        self.ruta_config = self.ruta_clase / "config.json"

        if not self.ruta_config.exists():
            raise FileNotFoundError(f"No se encontró 'config.json' en: {self.ruta_clase}")

        with open(self.ruta_config, "r", encoding="utf-8") as f:
            self.config = json.load(f)

        self.voz = self.config.get("voz", "es-AR-ElenaNeural")
        self.usar_mi_estilo = self.config.get("usar_mi_estilo", False)
        self.archivo_salida = self.ruta_clase / self.config.get("titulo_salida", "video_final.mp4")

        # Carpetas de trabajo temporales dentro de la clase
        self.dir_temp = self.ruta_clase / ".temp_build"
        self.dir_audios = self.dir_temp / "audios"
        self.dir_clips = self.dir_temp / "clips"
        for d in [self.dir_audios, self.dir_clips]:
            d.mkdir(parents=True, exist_ok=True)

    def _preparar_locucion(self, texto: str) -> str:
        loc = texto
        if self.usar_mi_estilo and loc.strip():
            loc = adaptar_texto_a_mi_estilo(loc, intensidad="conversacional")["texto_convertido"]
        # Aplicar pronunciación fonética para términos en inglés y marcas manuales {palabra|lectura}
        loc = aplicar_fonetica(loc, usar_diccionario_automatico=self.config.get("usar_diccionario_fonetico", True))
        
        # Si la voz seleccionada es clonada (XTTS-v2), aplicar seseo para neutralizar ceceo español
        voz_elegida = self.config.get("voz", "es-AR-ElenaNeural")
        if voz_elegida.startswith("clon:"):
            from diccionario_fonetico import aplicar_seseo_latino
            loc = aplicar_seseo_latino(loc)
        return loc

    async def _generar_audio(self, texto: str, destino: Path):
        locucion_final = self._preparar_locucion(texto)

        voz_elegida = self.config.get("voz", "es-AR-ElenaNeural")

        # Si es una voz clonada (empieza con "clon:")
        if voz_elegida.startswith("clon:"):
            archivo_clon = voz_elegida.split("clon:", 1)[1]
            try:
                print(f"   [🎙️ Clonador de Voz] Clonando voz con perfil ({archivo_clon})...")
                await asyncio.to_thread(sintetizar_con_voz_clonada, locucion_final, archivo_clon, destino)
                return
            except Exception as e:
                print(f"   [!] Aviso clonador falló ({e}), usando voz neuronal de respaldo (es-AR-ElenaNeural)...")
                voz_elegida = "es-AR-ElenaNeural"

        # Ajustar velocidad: para voces técnicas o tutoriales (como Jorge o Dalia) un -10% da claridad didáctica
        rate = "-10%" if "es-MX" in voz_elegida else "+0%"
        communicate = edge_tts.Communicate(locucion_final, voz_elegida, rate=rate)
        await communicate.save(str(destino))

    async def _generar_lote_audios(self, tareas_audio: list):
        """Genera una lista de tuplas (texto, ruta_destino) en una única corrutina."""
        for texto, destino in tareas_audio:
            await self._generar_audio(texto, destino)

    def _extraer_pasos_codigo(self, ruta_archivo: Path):
        """
        Extrae bloques anotados con:
        # [EXPLICAR: locución | ZOOM: editor | RESALTAR: 1-4 | TERMINAL: cmd | SALIDA: texto]
        o bien procesa automáticamente Notebooks (.ipynb) y archivos .py sin etiquetas.
        """
        if ruta_archivo.suffix.lower() == ".ipynb":
            pasos_nb = convertir_ipynb_a_pasos(ruta_archivo)
            return [
                {
                    "locucion": p["locucion"],
                    "codigo": p["codigo"].strip("\r\n") + "\n\n",
                    "zoom": p.get("zoom", "reset"),
                    "resaltar": None,
                    "cmd_term": p.get("terminal") or None,
                    "out_term": p.get("salida", "")
                }
                for p in pasos_nb
            ]

        contenido = ruta_archivo.read_text(encoding="utf-8")
        patron = r"(?:#|<!--)\s*\[EXPLICAR:\s*(.*?)\](?:\s*-->)?\n(.*?)(?=(?:(?:#|<!--)\s*\[EXPLICAR:)|$)"
        coincidencias = re.findall(patron, contenido, re.DOTALL)

        if not coincidencias:
            pasos_auto = auto_segmentar_py_sin_etiquetas(contenido, ruta_archivo.name)
            return [
                {
                    "locucion": p["locucion"],
                    "codigo": p["codigo"].strip("\r\n") + "\n\n",
                    "zoom": p.get("zoom", "reset"),
                    "resaltar": None,
                    "cmd_term": p.get("terminal") or None,
                    "out_term": p.get("salida", "")
                }
                for p in pasos_auto
            ]

        pasos = []
        for encabezado, cod in coincidencias:
            partes = [p.strip() for p in encabezado.split("|")]
            locucion = partes[0]

            zoom = "reset"
            resaltar = None
            cmd_term = None
            out_term = ""

            for p in partes[1:]:
                if p.upper().startswith("ZOOM:"):
                    zoom = p.split(":", 1)[1].strip().lower()
                elif p.upper().startswith("RESALTAR:"):
                    try:
                        r_vals = p.split(":", 1)[1].strip().split("-")
                        resaltar = (int(r_vals[0]), int(r_vals[1]))
                    except Exception:
                        resaltar = None
                elif p.upper().startswith("TERMINAL:"):
                    cmd_term = p.split(":", 1)[1].strip()
                elif p.upper().startswith("SALIDA:"):
                    out_term = p.split(":", 1)[1].strip()

            pasos.append({
                "locucion": locucion,
                "codigo": cod.strip("\r\n") + "\n\n",
                "zoom": zoom,
                "resaltar": resaltar,
                "cmd_term": cmd_term,
                "out_term": out_term
            })
        return pasos

    def _construir_arbol_explorador(self) -> list[dict]:
        """Construye la lista de carpetas y archivos del proyecto para mostrar en el sidebar de VS Code."""
        ignorar_dirs = {".temp_build", ".git", ".venv", "venv", "__pycache__", "node_modules"}
        ignorar_exts = {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mp3", ".wav", ".pdf", ".ppt", ".pptx", ".doc", ".docx"}
        ignorar_archivos = {"config.json", "guion_docente.md", "_slides_meta.json"}

        items = []

        def recorrer(directorio: Path, nivel: int):
            for entrada in sorted(directorio.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
                if entrada.name.startswith("_") or entrada.name in ignorar_dirs or entrada.name in ignorar_archivos:
                    continue
                if entrada.is_dir():
                    items.append({
                        "nombre": entrada.name,
                        "ruta": entrada.relative_to(self.ruta_clase).as_posix(),
                        "es_carpeta": True,
                        "nivel": nivel
                    })
                    recorrer(entrada, nivel + 1)
                else:
                    if entrada.suffix.lower() in ignorar_exts:
                        continue
                    items.append({
                        "nombre": entrada.name,
                        "ruta": entrada.relative_to(self.ruta_clase).as_posix(),
                        "es_carpeta": False,
                        "nivel": nivel
                    })

        recorrer(self.ruta_clase, 0)
        return items

    def _grabar_codigo_tipeado(self, ruta_codigo: Path, idx_bloque: int):
        pasos = self._extraer_pasos_codigo(ruta_codigo)
        if not pasos:
            print(f"   [!] Aviso: No se encontraron etiquetas [EXPLICAR: ...] en {ruta_codigo.name}")
            return None, []

        # 1. Pre-generar todos los audios antes de iniciar Playwright (evita conflicto de event loop)
        tareas_audio = []
        for i, paso in enumerate(pasos, start=1):
            audio_path = self.dir_audios / f"audio_b{idx_bloque}_paso_{i}.mp3"
            paso["audio_path"] = audio_path
            tareas_audio.append((paso["locucion"], audio_path))

        asyncio.run(self._generar_lote_audios(tareas_audio))

        audios_pasos = []
        for paso in pasos:
            a_clip = AudioFileClip(str(paso["audio_path"]))
            paso["duracion_audio"] = a_clip.duration
            a_clip.close()
            audios_pasos.append(paso["audio_path"])

        plantilla = (self.base_dir / "plantilla_editor.html").as_uri()

        # 2. Grabar tipeo y efectos visuales en Playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                record_video_dir=str(self.dir_clips),
                record_video_size={"width": 1920, "height": 1080},
                viewport={"width": 1920, "height": 1080}
            )
            page = context.new_page()
            page.goto(plantilla)
            arbol_items = self._construir_arbol_explorador()
            ruta_rel = ruta_codigo.resolve().relative_to(self.ruta_clase).as_posix()
            page.evaluate(
                "([nomProy, items, activo]) => setArbolProyecto(nomProy, items, activo)",
                [self.ruta_clase.name, arbol_items, ruta_rel]
            )
            page.wait_for_timeout(800)

            for i, paso in enumerate(pasos, start=1):
                duracion_audio = paso["duracion_audio"]
                codigo_a_tipear = paso["codigo"]

                if paso.get("zoom") and paso["zoom"] != "reset":
                    page.evaluate(f"aplicarZoom('{paso['zoom']}')")
                    page.wait_for_timeout(400)

                # Sincronización precisa en el navegador:
                # El tipeo se ejecuta en el tiempo exacto del audio dejando una pequeña pausa (0.8s) al final
                tiempo_tipeo_ms = int(max(1000, (duracion_audio - 0.8) * 1000))

                print(f"   -> Paso {i}/{len(pasos)} ({duracion_audio:.1f}s | zoom: {paso.get('zoom', 'reset')})...")
                # Ejecutar tipeo continuo sincronizado a 60 FPS dentro del browser
                page.evaluate(
                    "([cod, durMs]) => tipearCodigoSincronizado(cod, durMs)",
                    [codigo_a_tipear, tiempo_tipeo_ms]
                )

                if paso.get("resaltar"):
                    d, h = paso["resaltar"]
                    page.evaluate(f"resaltarLineas({d}, {h})")

                if paso.get("cmd_term"):
                    cmd = paso["cmd_term"]
                    salida = paso.get("out_term", "")
                    page.evaluate(f"ejecutarEnTerminal({json.dumps(cmd)}, {json.dumps(salida)})")

                # Pausa final para que la narración termine cómodamente mientras se mira el código listo
                tiempo_restante_ms = int(max(300, (duracion_audio * 1000) - tiempo_tipeo_ms))
                page.wait_for_timeout(tiempo_restante_ms)

                page.evaluate("limpiarResaltado()")
                page.evaluate("aplicarZoom('reset')")
                page.wait_for_timeout(300)

            video_raw = Path(page.video.path())
            context.close()
            browser.close()

        # 3. Concatenar audios de los pasos con ffmpeg
        audio_unido = self.dir_audios / f"audio_unido_b{idx_bloque}.m4a"
        if len(audios_pasos) == 1:
            cmd_audio = [
                FFMPEG_BINARY, "-y", "-i", str(audios_pasos[0]),
                "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "192k", str(audio_unido)
            ]
            subprocess.run(cmd_audio, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        elif len(audios_pasos) > 1:
            concat_txt = self.dir_audios / f"lista_audios_b{idx_bloque}.txt"
            concat_txt.write_text(
                "\n".join(f"file '{p.resolve().as_posix()}'" for p in audios_pasos),
                encoding="utf-8"
            )
            cmd_audio = [
                FFMPEG_BINARY, "-y", "-f", "concat", "-safe", "0",
                "-i", str(concat_txt),
                "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "192k", str(audio_unido)
            ]
            subprocess.run(cmd_audio, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            concat_txt.unlink(missing_ok=True)

        # 4. Obtener duraciones para emparejar video y audio sin desfasajes
        def get_dur(f):
            try:
                r = subprocess.run(
                    ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(f)],
                    capture_output=True, text=True, check=True
                )
                return float(r.stdout.strip())
            except Exception:
                return 1.0

        dur_v = get_dur(video_raw)
        dur_a = get_dur(audio_unido) if audio_unido.exists() else dur_v

        salida_mp4 = self.dir_clips / f"bloque_{idx_bloque:03d}.mp4"

        if dur_v >= dur_a:
            # Video más largo: extender audio con silencio
            cmd = [
                FFMPEG_BINARY, "-y",
                "-i", str(video_raw),
                "-i", str(audio_unido),
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-r", "25",
                "-c:a", "aac",
                "-af", "apad",
                "-shortest",
                "-movflags", "+faststart",
                str(salida_mp4)
            ]
        else:
            # Audio más largo: congelar último fotograma del video
            diff = dur_a - dur_v
            cmd = [
                FFMPEG_BINARY, "-y",
                "-i", str(video_raw),
                "-i", str(audio_unido),
                "-vf", f"tpad=stop_mode=clone:stop_duration={diff:.3f}",
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-r", "25",
                "-c:a", "copy",
                "-movflags", "+faststart",
                str(salida_mp4)
            ]

        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        if video_raw.exists():
            video_raw.unlink(missing_ok=True)
        if audio_unido.exists():
            audio_unido.unlink(missing_ok=True)

        return salida_mp4

    def procesar(self, limpiar_temp: bool = False):
        bloques = self.config.get("bloques", [])
        clips_finales = []

        print(f"\n=== Iniciando generación de clase: {self.ruta_clase.name} ===")

        for idx, bloque in enumerate(bloques, start=1):
            tipo = bloque.get("tipo")
            clip_salida = self.dir_clips / f"bloque_{idx:03d}.mp4"

            # Reutilizar si ya fue generado previamente
            if clip_salida.exists() and clip_salida.stat().st_size > 5000:
                print(f"[{idx}/{len(bloques)}] Reutilizando bloque listo: {clip_salida.name}")
                clips_finales.append(clip_salida)
                continue

            if tipo == "slide":
                img_path = self.ruta_clase / bloque["archivo"]
                locucion = bloque.get("locucion", "")
                audio_path = self.dir_audios / f"audio_slide_{idx}.mp3"

                print(f"[{idx}/{len(bloques)}] Slide: {img_path.name}")
                if not audio_path.exists() or audio_path.stat().st_size < 500:
                    asyncio.run(self._generar_audio(locucion, audio_path))

                # Renderizar slide estandarizada a 1920x1080 25fps con faststart
                cmd = [
                    FFMPEG_BINARY, "-y",
                    "-loop", "1",
                    "-framerate", "25",
                    "-i", str(img_path),
                    "-i", str(audio_path),
                    "-c:v", "libx264",
                    "-tune", "stillimage",
                    "-pix_fmt", "yuv420p",
                    "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1",
                    "-c:a", "aac",
                    "-ar", "44100",
                    "-ac", "2",
                    "-b:a", "192k",
                    "-shortest",
                    "-movflags", "+faststart",
                    str(clip_salida)
                ]
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                clips_finales.append(clip_salida)

            elif tipo == "codigo_anotado":
                arch_cod = self.ruta_clase / bloque["archivo"]
                print(f"[{idx}/{len(bloques)}] Código explicado en vivo: {arch_cod.name}")
                clip_tipeado = self._grabar_codigo_tipeado(arch_cod, idx)
                if clip_tipeado and clip_tipeado.exists():
                    clips_finales.append(clip_tipeado)

        if not clips_finales:
            print("No se generaron clips para el video.")
            return

        print(f"\nConcatenando {len(clips_finales)} bloques en el MP4 definitivo con FFmpeg (sin pérdida ni desfasajes)...")
        lista_final_txt = self.dir_clips / "lista_concat_final.txt"
        lista_final_txt.write_text(
            "\n".join(f"file '{p.resolve().as_posix()}'" for p in clips_finales),
            encoding="utf-8"
        )

        temp_salida = self.archivo_salida.with_suffix(".temp.mp4")
        cmd_concat = [
            FFMPEG_BINARY, "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(lista_final_txt),
            "-c", "copy",
            "-movflags", "+faststart",
            str(temp_salida)
        ]
        subprocess.run(cmd_concat, check=True)

        if self.archivo_salida.exists():
            self.archivo_salida.unlink()
        temp_salida.rename(self.archivo_salida)
        lista_final_txt.unlink(missing_ok=True)

        if limpiar_temp and self.dir_temp.exists():
            shutil.rmtree(self.dir_temp, ignore_errors=True)

        mb = self.archivo_salida.stat().st_size / (1024 * 1024)
        print(f"\n¡LISTO! Video guardado y 100% verificado: {self.archivo_salida} ({mb:.2f} MB)\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python generador_universal.py <carpeta_de_la_clase>")
        print("Ejemplo: python generador_universal.py clases/clase12")
        sys.exit(1)

    carpeta = Path(sys.argv[1])
    generador = GeneradorVideoUniversal(carpeta)
    generador.procesar()
