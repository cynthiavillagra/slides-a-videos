import os
import re
import sys
import json
import zipfile
import asyncio
from pathlib import Path
from aiohttp import web
import edge_tts
from estilo_habla import adaptar_texto_a_mi_estilo, cargar_modelo_estilo, entrenar_modelo_estilo_desde_textos
from clonador_voz import listar_perfiles_voz, guardar_muestra_voz, eliminar_perfil_voz, sintetizar_con_voz_clonada
from diccionario_fonetico import aplicar_fonetica, cargar_diccionario, guardar_diccionario
from procesador_entradas import (
    convertir_pdf_a_slides,
    convertir_ppt_a_slides,
    extraer_texto_guion,
    convertir_ipynb_a_pasos,
    auto_segmentar_py_sin_etiquetas,
    emparejar_guion_con_slides_y_codigo,
    parsear_guion_estructurado
)

BASE_DIR = Path(__file__).resolve().parent
CLASES_DIR = BASE_DIR / "clases"
CLASES_DIR.mkdir(exist_ok=True)

estado_procesos = {}


def extraer_pasos_codigo(contenido: str, nombre_archivo: str = "codigo.py"):
    patron = r"(?:#|<!--)\s*\[EXPLICAR:\s*(.*?)\](?:\s*-->)?\n(.*?)(?=(?:(?:#|<!--)\s*\[EXPLICAR:)|$)"
    coincidencias = re.findall(patron, contenido, re.DOTALL)
    if not coincidencias:
        return auto_segmentar_py_sin_etiquetas(contenido, nombre_archivo)

    pasos = []
    for encabezado, cod in coincidencias:
        partes = [p.strip() for p in encabezado.split("|")]
        locucion = partes[0]
        zoom = "reset"
        resaltar = ""
        terminal = ""
        salida = ""
        for p in partes[1:]:
            if p.upper().startswith("ZOOM:"):
                zoom = p.split(":", 1)[1].strip().lower()
            elif p.upper().startswith("RESALTAR:"):
                resaltar = p.split(":", 1)[1].strip()
            elif p.upper().startswith("TERMINAL:"):
                terminal = p.split(":", 1)[1].strip()
            elif p.upper().startswith("SALIDA:"):
                salida = p.split(":", 1)[1].strip()
        pasos.append({
            "locucion": locucion,
            "codigo": cod.strip("\r\n"),
            "zoom": zoom,
            "resaltar": resaltar,
            "terminal": terminal,
            "salida": salida
        })
    return pasos


def reconstruir_codigo_anotado(pasos: list) -> str:
    bloques = []
    for p in pasos:
        loc = (p.get("locucion") or "Explicación del código.").strip()
        partes = [loc]
        zoom = (p.get("zoom") or "reset").strip()
        if zoom and zoom != "reset":
            partes.append(f"ZOOM: {zoom}")
        resaltar = (p.get("resaltar") or "").strip()
        if resaltar:
            partes.append(f"RESALTAR: {resaltar}")
        terminal = (p.get("terminal") or "").strip()
        if terminal:
            partes.append(f"TERMINAL: {terminal}")
        salida = (p.get("salida") or "").strip()
        if salida:
            partes.append(f"SALIDA: {salida}")
        encabezado = " | ".join(partes)
        cod = (p.get("codigo") or "").strip("\r\n")
        bloques.append(f"# [EXPLICAR: {encabezado}]\n{cod}")
    return "\n\n".join(bloques) + "\n"


async def index(request):
    return web.FileResponse(BASE_DIR / "interfaz_web.html")


async def listar_clases(request):
    clases = [d.name for d in sorted(CLASES_DIR.iterdir()) if d.is_dir()]
    modelo = cargar_modelo_estilo()
    voces_clonadas = listar_perfiles_voz()
    return web.json_response({
        "clases": clases,
        "estilo_entrenado": bool(modelo.get("entrenado")),
        "muletillas": (modelo.get("muletillas_personalizadas") or [])[:8],
        "metricas_estilo": modelo.get("metricas", {}),
        "voces_clonadas": voces_clonadas
    })


async def crear_clase(request):
    data = await request.json()
    nombre = re.sub(r"[^a-zA-Z0-9_-]", "_", data.get("nombre", "").strip())
    if not nombre:
        return web.json_response({"error": "Nombre inválido"}, status=400)
    ruta = CLASES_DIR / nombre
    ruta.mkdir(parents=True, exist_ok=True)
    cfg_path = ruta / "config.json"
    if not cfg_path.exists():
        cfg = {
            "titulo_salida": f"{nombre}_video_final.mp4",
            "voz": "es-AR-ElenaNeural",
            "usar_mi_estilo": True,
            "bloques": []
        }
        cfg_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    return web.json_response({"ok": True, "nombre": nombre})


IGNORAR_DIRS_PROYECTO = {".temp_build", ".git", ".venv", "venv", "__pycache__", "node_modules"}


def _es_ruta_ignorada(ruta_rel: Path) -> bool:
    return any(p in IGNORAR_DIRS_PROYECTO or p.startswith("_") for p in ruta_rel.parts)


async def detalle_clase(request):
    nombre = request.match_info["nombre"]
    ruta = CLASES_DIR / nombre
    if not ruta.exists():
        return web.json_response({"error": "No existe la clase"}, status=404)

    cfg_path = ruta / "config.json"
    if cfg_path.exists():
        config = json.loads(cfg_path.read_text(encoding="utf-8"))
    else:
        config = {
            "titulo_salida": f"{nombre}_video_final.mp4",
            "voz": "es-AR-ElenaNeural",
            "usar_mi_estilo": True,
            "bloques": []
        }

    slides = []
    codigos = {}
    videos = []

    for f in sorted(ruta.rglob("*")):
        if f.is_file():
            rel = f.relative_to(ruta)
            if _es_ruta_ignorada(rel):
                continue
            rel_str = rel.as_posix()
            ext = f.suffix.lower()
            if f.parent == ruta and ext in [".png", ".jpg", ".jpeg", ".webp"]:
                slides.append(f.name)
            elif ext in [".py", ".js", ".ts", ".html", ".css", ".sql", ".sh"]:
                texto = f.read_text(encoding="utf-8", errors="replace")
                codigos[rel_str] = {
                    "raw": texto,
                    "pasos": extraer_pasos_codigo(texto, f.name)
                }
            elif ext == ".ipynb":
                pasos_nb = convertir_ipynb_a_pasos(f)
                codigos[rel_str] = {
                    "raw": reconstruir_codigo_anotado(pasos_nb),
                    "pasos": pasos_nb
                }
            elif f.parent == ruta and ext == ".mp4":
                videos.append(f.name)

    guion_path = ruta / "guion_docente.md"
    guion_bruto = guion_path.read_text(encoding="utf-8") if guion_path.exists() else ""

    salida_mp4 = config.get("titulo_salida", "video_final.mp4")
    tiene_video_final = (ruta / salida_mp4).exists()

    return web.json_response({
        "nombre": nombre,
        "config": config,
        "slides": slides,
        "codigos": codigos,
        "guion_bruto": guion_bruto,
        "tiene_video_final": tiene_video_final,
        "video_final": salida_mp4,
        "videos": videos
    })


async def api_adaptar_estilo(request):
    data = await request.json()
    texto = data.get("texto", "")
    intensidad = data.get("intensidad", "conversacional")
    res = adaptar_texto_a_mi_estilo(texto, intensidad=intensidad)
    return web.json_response(res)


async def api_entrenar_estilo(request):
    """Permite a cualquier usuario subir sus propias transcripciones para entrenar su propio estilo."""
    reader = await request.multipart()
    textos = []
    fuentes = []
    while True:
        part = await reader.next()
        if part is None:
            break
        if part.filename:
            fn = part.filename
            content_bytes = await part.read()
            txt = content_bytes.decode("utf-8", errors="replace")
            if txt.strip():
                textos.append(txt)
                fuentes.append(fn)

    if not textos:
        return web.json_response({"error": "No se recibieron transcripciones con texto válido"}, status=400)

    try:
        nuevo_modelo = entrenar_modelo_estilo_desde_textos(textos, fuentes)
        return web.json_response({
            "ok": True,
            "muletillas": nuevo_modelo.get("muletillas_personalizadas", []),
            "metricas": nuevo_modelo.get("metricas", {})
        })
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def subir_muestra_voz_clon(request):
    """Sube un audio con un nombre personalizado para registrar la voz clonada."""
    reader = await request.multipart()
    nombre_perfil = "Mi Voz"
    bytes_audio = None
    filename = ""

    while True:
        part = await reader.next()
        if part is None:
            break
        if part.name == "nombre":
            nombre_perfil = (await part.text()).strip() or "Mi Voz"
        elif part.filename:
            filename = part.filename
            bytes_audio = await part.read()

    if bytes_audio:
        guardar_muestra_voz(nombre_perfil, filename, bytes_audio)

    return web.json_response({"ok": True, "voces_clonadas": listar_perfiles_voz()})


async def eliminar_voz_clon(request):
    data = await request.json()
    archivo = data.get("archivo", "")
    eliminar_perfil_voz(archivo)
    return web.json_response({"ok": True, "voces_clonadas": listar_perfiles_voz()})


async def api_probar_voz(request):
    try:
        data = await request.json()
    except Exception:
        raw = await request.read()
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            data = json.loads(raw.decode("latin-1", errors="replace"))

    voz = data.get("voz", "es-AR-ElenaNeural")
    texto = data.get("texto", "Hola, esta es una prueba de audio para la narración de tu clase.")
    locucion_procesada = aplicar_fonetica(texto)
    destino = BASE_DIR / "temp_audio_prueba.wav"
    try:
        if voz.startswith("clon:"):
            archivo_clon = voz.split("clon:", 1)[1]
            await asyncio.to_thread(sintetizar_con_voz_clonada, locucion_procesada, archivo_clon, destino)
        else:
            rate = "-10%" if "es-MX" in voz else "+0%"
            comm = edge_tts.Communicate(locucion_procesada, voz, rate=rate)
            await comm.save(str(destino))
        return web.FileResponse(destino, headers={"Cache-Control": "no-cache"})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def api_obtener_diccionario_fonetico(request):
    return web.json_response({"ok": True, "diccionario": cargar_diccionario()})


async def api_guardar_diccionario_fonetico(request):
    data = await request.json()
    dic = data.get("diccionario", {})
    if isinstance(dic, dict):
        guardar_diccionario(dic)
    return web.json_response({"ok": True, "diccionario": cargar_diccionario()})


async def guardar_clase(request):
    nombre = request.match_info["nombre"]
    ruta = CLASES_DIR / nombre
    ruta.mkdir(parents=True, exist_ok=True)
    data = await request.json()

    if "config" in data:
        (ruta / "config.json").write_text(
            json.dumps(data["config"], indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

    if "guion_bruto" in data:
        (ruta / "guion_docente.md").write_text(data["guion_bruto"], encoding="utf-8")

    if "codigos_editados" in data:
        for arch, info in data["codigos_editados"].items():
            # Si era un .ipynb y lo editaron, guardamos un .py anotado listo o actualizamos los pasos
            destino = ruta / arch
            if destino.suffix.lower() == ".ipynb":
                destino = ruta / (destino.stem + "_notebook.py")
            if "pasos" in info and info["pasos"]:
                destino.write_text(reconstruir_codigo_anotado(info["pasos"]), encoding="utf-8")
            elif "raw" in info:
                destino.write_text(info["raw"], encoding="utf-8")

    return web.json_response({"ok": True})


async def _recibir_archivos_multipart(request, carpeta_destino: Path) -> list[Path]:
    reader = await request.multipart()
    guardados = []
    while True:
        part = await reader.next()
        if part is None:
            break
        if part.filename:
            filename = Path(part.filename).name
            destino = carpeta_destino / filename
            with open(destino, "wb") as f:
                while True:
                    chunk = await part.read_chunk()
                    if not chunk:
                        break
                    f.write(chunk)
            guardados.append(destino)
    return guardados


async def subir_slides(request):
    """Acepta .pdf, .ppt, .pptx o imágenes (.png, .jpg, .webp) y extrae cada slide como PNG + su texto."""
    nombre = request.match_info["nombre"]
    ruta = CLASES_DIR / nombre
    ruta.mkdir(parents=True, exist_ok=True)

    meta_path = ruta / "_slides_meta.json"
    meta_slides = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}

    archivos = await _recibir_archivos_multipart(request, ruta)
    slides_generadas = []
    notas_extraidas = []

    for arch in archivos:
        ext = arch.suffix.lower()
        if ext == ".pdf":
            nuevas, textos = await asyncio.to_thread(convertir_pdf_a_slides, arch, ruta)
            slides_generadas.extend(nuevas)
            for s_nom, s_txt in zip(nuevas, textos):
                meta_slides[s_nom] = s_txt
            arch.unlink(missing_ok=True)
        elif ext in [".ppt", ".pptx"]:
            nuevas, textos, notas = await asyncio.to_thread(convertir_ppt_a_slides, arch, ruta)
            slides_generadas.extend(nuevas)
            for s_nom, s_txt in zip(nuevas, textos):
                meta_slides[s_nom] = s_txt
            notas_extraidas.extend([n for n in notas if n])
            arch.unlink(missing_ok=True)
        elif ext in [".png", ".jpg", ".jpeg", ".webp"]:
            slides_generadas.append(arch.name)

    meta_path.write_text(json.dumps(meta_slides, ensure_ascii=False, indent=2), encoding="utf-8")

    # Si la presentación tenía notas de orador y no había guion, guardarlas como sugerencia
    guion_path = ruta / "guion_docente.md"
    if notas_extraidas and not guion_path.exists():
        guion_path.write_text("\n\n".join(notas_extraidas), encoding="utf-8")

    return web.json_response({"ok": True, "slides": slides_generadas})


async def auto_emparejar_clase(request):
    """Cruza automáticamente el texto del guion con el texto detectado en las slides y el código."""
    nombre = request.match_info["nombre"]
    ruta = CLASES_DIR / nombre
    data = await request.json()
    raw_guion = data.get("guion", "")
    if isinstance(raw_guion, list):
        guion_texto = "\n".join(str(x) for x in raw_guion)
    else:
        guion_texto = str(raw_guion or "")

    meta_path = ruta / "_slides_meta.json"
    meta_slides = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}

    slides = []
    codigos = []
    for f in sorted(ruta.rglob("*")):
        if f.is_file():
            rel = f.relative_to(ruta)
            if _es_ruta_ignorada(rel):
                continue
            ext = f.suffix.lower()
            if f.parent == ruta and ext in [".png", ".jpg", ".jpeg", ".webp"]:
                slides.append(f.name)
            elif ext in [".py", ".js", ".ts", ".html", ".sql"]:
                codigos.append(rel.as_posix())

    estructurado = parsear_guion_estructurado(guion_texto, slides, codigos)
    if estructurado is not None:
        bloques, locuciones_cod = estructurado
        for arch_c, locs in locuciones_cod.items():
            ruta_c = ruta / arch_c
            if ruta_c.exists():
                txt_c = ruta_c.read_text(encoding="utf-8", errors="replace")
                # Si el guion especifica exactamente N párrafos para este código, re-segmentar en N partes
                txt_sin_etiquetas = re.sub(r"(?:#|<!--)\s*\[EXPLICAR:.*?\](?:\s*-->)?\n?", "", txt_c)
                pasos_c = auto_segmentar_py_sin_etiquetas(txt_sin_etiquetas, ruta_c.name, cantidad_pasos_deseada=len(locs))
                if not pasos_c:
                    pasos_c = extraer_pasos_codigo(txt_c, ruta_c.name)
                # Asignar cada párrafo exacto del guion a cada fragmento de código
                for idx_l, loc_txt in enumerate(locs):
                    if idx_l < len(pasos_c):
                        pasos_c[idx_l]["locucion"] = loc_txt
                ruta_c.write_text(reconstruir_codigo_anotado(pasos_c), encoding="utf-8")

        # Guardar automáticamente la nueva secuencia en config.json
        cfg_path = ruta / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
        cfg["bloques"] = bloques
        cfg_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
        return web.json_response({"ok": True, "bloques": bloques})

    bloques = emparejar_guion_con_slides_y_codigo(guion_texto, slides, meta_slides, codigos)
    cfg_path = ruta / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
    cfg["bloques"] = bloques
    cfg_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    return web.json_response({"ok": True, "bloques": bloques})


async def subir_guion(request):
    """Acepta un guion en .pdf, .docx, .doc, .md o .txt y extrae todo su texto a guion_docente.md."""
    nombre = request.match_info["nombre"]
    ruta = CLASES_DIR / nombre
    ruta.mkdir(parents=True, exist_ok=True)

    archivos = await _recibir_archivos_multipart(request, ruta)
    textos = []
    for arch in archivos:
        txt = await asyncio.to_thread(extraer_texto_guion, arch)
        if txt:
            textos.append(txt)
        if arch.name != "guion_docente.md":
            arch.unlink(missing_ok=True)

    guion_completo = "\n\n".join(textos)
    if guion_completo:
        (ruta / "guion_docente.md").write_text(guion_completo, encoding="utf-8")

    return web.json_response({"ok": True, "guion": guion_completo})


def _preparar_archivo_codigo_en_disco(arch: Path, ruta_clase: Path) -> str | None:
    ext = arch.suffix.lower()
    if ext == ".ipynb":
        pasos = convertir_ipynb_a_pasos(arch)
        py_destino = arch.with_suffix(".py")
        py_destino.write_text(reconstruir_codigo_anotado(pasos), encoding="utf-8")
        arch.unlink(missing_ok=True)
        return py_destino.relative_to(ruta_clase).as_posix()
    elif ext in [".py", ".js", ".ts", ".html", ".sql"]:
        contenido = arch.read_text(encoding="utf-8", errors="replace")
        if ext == ".py" and "[EXPLICAR:" not in contenido:
            pasos = auto_segmentar_py_sin_etiquetas(contenido, arch.name)
            arch.write_text(reconstruir_codigo_anotado(pasos), encoding="utf-8")
        return arch.relative_to(ruta_clase).as_posix()
    return None


async def subir_codigo(request):
    """
    Acepta:
    - Archivos .zip con toda una carpeta de proyecto de VS Code
    - Una carpeta entera seleccionada desde el navegador (conservando subcarpetas)
    - Archivos sueltos (.py, .ipynb, .html, .js, .sql)
    """
    nombre = request.match_info["nombre"]
    ruta = CLASES_DIR / nombre
    ruta.mkdir(parents=True, exist_ok=True)

    reader = await request.multipart()
    guardados = []
    relpath_actual = None

    while True:
        part = await reader.next()
        if part is None:
            break
        if part.name == "relpath":
            relpath_actual = (await part.text()).strip().replace("\\", "/")
        elif part.filename:
            rel_limpio = relpath_actual or Path(part.filename).name
            relpath_actual = None
            partes_seguras = [p for p in Path(rel_limpio).parts if p not in ("..", "/", "\\")]
            if any(p in IGNORAR_DIRS_PROYECTO for p in partes_seguras):
                continue
            destino = ruta.joinpath(*partes_seguras)
            destino.parent.mkdir(parents=True, exist_ok=True)
            with open(destino, "wb") as f:
                while True:
                    chunk = await part.read_chunk()
                    if not chunk:
                        break
                    f.write(chunk)
            guardados.append(destino)

    procesados = []

    for arch in guardados:
        ext = arch.suffix.lower()
        if ext == ".zip":
            with zipfile.ZipFile(arch, "r") as zf:
                for member in zf.infolist():
                    if member.is_dir():
                        continue
                    partes_m = [p for p in Path(member.filename).parts if p not in ("..", "/", "\\")]
                    if not partes_m or any(p in IGNORAR_DIRS_PROYECTO or p.startswith(".") for p in partes_m):
                        continue
                    dest_m = ruta.joinpath(*partes_m)
                    dest_m.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(member) as src, open(dest_m, "wb") as dst:
                        dst.write(src.read())
                    rel_proc = await asyncio.to_thread(_preparar_archivo_codigo_en_disco, dest_m, ruta)
                    if rel_proc:
                        procesados.append(rel_proc)
            arch.unlink(missing_ok=True)
        else:
            rel_proc = await asyncio.to_thread(_preparar_archivo_codigo_en_disco, arch, ruta)
            if rel_proc:
                procesados.append(rel_proc)

    return web.json_response({"ok": True, "codigos": procesados})


async def eliminar_archivo_clase(request):
    """Elimina una slide individual, todas las slides, o un archivo de código de la clase."""
    nombre = request.match_info["nombre"]
    ruta = CLASES_DIR / nombre
    if not ruta.exists():
        return web.json_response({"error": "No existe la clase"}, status=404)

    data = await request.json()
    tipo = data.get("tipo")  # "slide", "todas_slides", "codigo", "todos_codigos"
    archivo = data.get("archivo", "")

    cfg_path = ruta / "config.json"
    config = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {"bloques": []}

    if tipo == "todas_slides":
        for f in ruta.iterdir():
            if f.is_file() and f.suffix.lower() in [".png", ".jpg", ".jpeg", ".webp"]:
                f.unlink(missing_ok=True)
        (ruta / "_slides_meta.json").unlink(missing_ok=True)
        config["bloques"] = [b for b in config.get("bloques", []) if b.get("tipo") != "slide"]

    elif tipo == "slide" and archivo:
        objetivo = (ruta / Path(archivo).name).resolve()
        if objetivo.parent == ruta.resolve() and objetivo.exists():
            objetivo.unlink(missing_ok=True)
        config["bloques"] = [
            b for b in config.get("bloques", [])
            if not (b.get("tipo") == "slide" and b.get("archivo") == archivo)
        ]

    elif tipo == "codigo" and archivo:
        partes = [p for p in Path(archivo).parts if p not in ("..", "/", "\\")]
        objetivo = ruta.joinpath(*partes).resolve()
        if str(objetivo).startswith(str(ruta.resolve())) and objetivo.exists():
            objetivo.unlink(missing_ok=True)
        config["bloques"] = [
            b for b in config.get("bloques", [])
            if not (b.get("tipo") == "codigo_anotado" and b.get("archivo") == archivo)
        ]

    elif tipo == "todos_codigos":
        import shutil
        for f in list(ruta.iterdir()):
            if f.is_dir() and f.name != ".temp_build":
                shutil.rmtree(f, ignore_errors=True)
            elif f.is_file() and f.suffix.lower() in [".py", ".ipynb", ".js", ".ts", ".html", ".css", ".sql", ".sh"]:
                f.unlink(missing_ok=True)
        config["bloques"] = [b for b in config.get("bloques", []) if b.get("tipo") != "codigo_anotado"]

    cfg_path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    return web.json_response({"ok": True})


async def servir_archivo_clase(request):
    nombre = request.match_info["nombre"]
    archivo = request.match_info["archivo"]
    ruta = (CLASES_DIR / nombre / archivo).resolve()
    if not str(ruta).startswith(str((CLASES_DIR / nombre).resolve())) or not ruta.exists():
        return web.Response(status=404)
    return web.FileResponse(ruta)


async def iniciar_generacion(request):
    nombre = request.match_info["nombre"]
    ruta = CLASES_DIR / nombre
    if not ruta.exists():
        return web.json_response({"error": "No existe la clase"}, status=404)

    if estado_procesos.get(nombre, {}).get("corriendo"):
        return web.json_response({"error": "Ya se está generando el video para esta clase"}, status=400)

    estado_procesos[nombre] = {
        "corriendo": True,
        "logs": [f"Iniciando generación de video para '{nombre}'..."],
        "exito": None
    }

    async def correr_subproceso():
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-u", str(BASE_DIR / "generador_universal.py"), str(ruta),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(BASE_DIR)
        )
        while True:
            linea = await proc.stdout.readline()
            if not linea:
                break
            texto = linea.decode("utf-8", errors="replace").rstrip()
            if texto:
                estado_procesos[nombre]["logs"].append(texto)

        rc = await proc.wait()
        estado_procesos[nombre]["corriendo"] = False
        estado_procesos[nombre]["exito"] = (rc == 0)
        if rc == 0:
            estado_procesos[nombre]["logs"].append("✅ ¡Renderizado finalizado con éxito!")
        else:
            estado_procesos[nombre]["logs"].append(f"❌ El proceso terminó con código de error {rc}")

    asyncio.create_task(correr_subproceso())
    return web.json_response({"ok": True})


async def estado_generacion(request):
    nombre = request.match_info["nombre"]
    info = estado_procesos.get(nombre, {"corriendo": False, "logs": [], "exito": None})
    return web.json_response(info)


def crear_app():
    app = web.Application(client_max_size=1024 ** 3)
    app.router.add_get("/", index)
    app.router.add_get("/api/clases", listar_clases)
    app.router.add_post("/api/clases", crear_clase)
    app.router.add_post("/api/adaptar-estilo", api_adaptar_estilo)
    app.router.add_post("/api/entrenar-estilo", api_entrenar_estilo)
    app.router.add_post("/api/subir-muestra-voz", subir_muestra_voz_clon)
    app.router.add_post("/api/eliminar-voz-clon", eliminar_voz_clon)
    app.router.add_post("/api/probar-voz", api_probar_voz)
    app.router.add_get("/api/diccionario-fonetico", api_obtener_diccionario_fonetico)
    app.router.add_post("/api/diccionario-fonetico", api_guardar_diccionario_fonetico)
    app.router.add_get("/api/clases/{nombre}", detalle_clase)
    app.router.add_post("/api/clases/{nombre}/guardar", guardar_clase)
    app.router.add_post("/api/clases/{nombre}/subir-slides", subir_slides)
    app.router.add_post("/api/clases/{nombre}/subir-guion", subir_guion)
    app.router.add_post("/api/clases/{nombre}/subir-codigo", subir_codigo)
    app.router.add_post("/api/clases/{nombre}/auto-emparejar", auto_emparejar_clase)
    app.router.add_post("/api/clases/{nombre}/eliminar-archivo", eliminar_archivo_clase)
    app.router.add_post("/api/clases/{nombre}/generar", iniciar_generacion)
    app.router.add_get("/api/clases/{nombre}/estado", estado_generacion)
    app.router.add_get("/clases/{nombre}/{archivo}", servir_archivo_clase)
    return app


if __name__ == "__main__":
    puerto = int(os.environ.get("PORT", 8080))
    print(f"\n=======================================================")
    print(f" Estudio Web de Videos iniciado en: http://localhost:{puerto}")
    print(f"=======================================================\n")
    web.run_app(crear_app(), host="127.0.0.1", port=puerto, print=None)
