import re
import json
import subprocess
from pathlib import Path
import fitz  # PyMuPDF
from docx import Document
from pptx import Presentation
from PIL import Image, ImageDraw, ImageFont


def convertir_pdf_a_slides(ruta_pdf: Path, carpeta_destino: Path) -> tuple[list[str], list[str]]:
    """Convierte cada página de un PDF en imágenes PNG de alta definición y extrae el texto de cada slide."""
    doc = fitz.open(str(ruta_pdf))
    generadas = []
    textos_slides = []
    prefijo = re.sub(r"[^a-zA-Z0-9_-]", "_", ruta_pdf.stem)
    for idx, page in enumerate(doc, start=1):
        zoom = 2.0
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        nombre_png = f"{prefijo}_slide_{idx:02d}.png"
        destino = carpeta_destino / nombre_png
        pix.save(str(destino))
        generadas.append(nombre_png)
        textos_slides.append(page.get_text("text").strip())
    doc.close()
    return generadas, textos_slides


def _renderizar_slide_pptx_fallback(slide, destino_png: Path, num_slide: int):
    """Renderiza una diapositiva de PowerPoint a 1920x1080 si Office no está instalado."""
    W, H = 1920, 1080
    img = Image.new("RGB", (W, H), color=(15, 23, 42))
    draw = ImageDraw.Draw(img)

    # Barra decorativa superior
    draw.rectangle([0, 0, W, 14], fill=(56, 189, 248))

    try:
        font_titulo = ImageFont.truetype("arialbd.ttf", 54)
        font_texto = ImageFont.truetype("arial.ttf", 34)
    except Exception:
        font_titulo = ImageFont.load_default()
        font_texto = ImageFont.load_default()

    textos = []
    imagenes_extraidas = []

    for shape in slide.shapes:
        if shape.has_text_frame:
            for p in shape.text_frame.paragraphs:
                t = p.text.strip()
                if t:
                    textos.append(t)
        if shape.shape_type == 13:  # PICTURE
            try:
                blob = shape.image.blob
                import io
                im_emb = Image.open(io.BytesIO(blob)).convert("RGB")
                imagenes_extraidas.append(im_emb)
            except Exception:
                pass

    # Si la slide es básicamente una imagen a pantalla completa, usarla
    if len(imagenes_extraidas) == 1 and len(textos) <= 1:
        im_base = imagenes_extraidas[0].resize((W, H))
        im_base.save(str(destino_png))
        return

    titulo = textos[0] if textos else f"Diapositiva {num_slide}"
    cuerpo = textos[1:] if len(textos) > 1 else []

    draw.text((100, 90), titulo[:75], fill=(248, 250, 252), font=font_titulo)
    draw.line([100, 175, W - 100, 175], fill=(51, 65, 85), width=3)

    y = 230
    max_w_texto = 1000 if imagenes_extraidas else 1700
    for linea in cuerpo[:12]:
        # Envolver líneas largas
        palabras = linea.split()
        actual = "• "
        for pal in palabras:
            if len(actual + pal) > (52 if imagenes_extraidas else 85):
                draw.text((110, y), actual, fill=(203, 213, 225), font=font_texto)
                y += 50
                actual = "   " + pal + " "
            else:
                actual += pal + " "
        if actual.strip():
            draw.text((110, y), actual, fill=(203, 213, 225), font=font_texto)
            y += 60
        if y > H - 120:
            break

    if imagenes_extraidas:
        im_side = imagenes_extraidas[0]
        im_side.thumbnail((680, 680))
        img.paste(im_side, (W - im_side.width - 100, 230))

    img.save(str(destino_png))


def convertir_ppt_a_slides(ruta_ppt: Path, carpeta_destino: Path) -> tuple[list[str], list[str], list[str]]:
    """
    Convierte un archivo .ppt / .pptx en imágenes PNG (slide_01.png, ...)
    y extrae tanto el texto visible de cada slide como las notas del orador.
    """
    prefijo = re.sub(r"[^a-zA-Z0-9_-]", "_", ruta_ppt.stem)
    pdf_temp = carpeta_destino / f"_{prefijo}_temp.pdf"
    generadas = []
    textos_slides = []
    notas_orador = []

    # 1. Intentar exportar a PDF vía PowerPoint en Windows para máxima fidelidad visual
    ps_script = f"""
    $ErrorActionPreference = 'Stop'
    $ppt = New-Object -ComObject PowerPoint.Application
    $pres = $ppt.Presentations.Open('{str(ruta_ppt.resolve())}', $true, $false, $false)
    $pres.SaveAs('{str(pdf_temp.resolve())}', 32)
    $pres.Close()
    $ppt.Quit()
    """
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=45,
            check=True
        )
        if pdf_temp.exists():
            generadas, textos_slides = convertir_pdf_a_slides(pdf_temp, carpeta_destino)
            pdf_temp.unlink(missing_ok=True)
    except Exception:
        if pdf_temp.exists():
            pdf_temp.unlink(missing_ok=True)

    # 2. Extraer notas de orador y texto de cada slide desde python-pptx
    if ruta_ppt.suffix.lower() == ".pptx":
        prs = Presentation(str(ruta_ppt))
        textos_pptx = []
        for idx, slide in enumerate(prs.slides, start=1):
            nota = ""
            if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
                nota = slide.notes_slide.notes_text_frame.text.strip()
            notas_orador.append(nota)

            txt_s = []
            for shape in slide.shapes:
                if shape.has_text_frame:
                    txt_s.append(shape.text_frame.text.strip())
            textos_pptx.append(" ".join(t for t in txt_s if t))

            if not generadas:
                nombre_png = f"{prefijo}_slide_{idx:02d}.png"
                destino_png = carpeta_destino / nombre_png
                _renderizar_slide_pptx_fallback(slide, destino_png, idx)
                generadas.append(nombre_png)
        if not textos_slides:
            textos_slides = textos_pptx

    return generadas, textos_slides, notas_orador


def extraer_texto_guion(ruta_archivo: Path) -> str:
    """Extrae el texto de un guion docente en formato .txt, .md, .docx, .doc o .pdf."""
    ext = ruta_archivo.suffix.lower()

    if ext in [".txt", ".md"]:
        return ruta_archivo.read_text(encoding="utf-8", errors="replace").strip()

    if ext == ".pdf":
        doc = fitz.open(str(ruta_archivo))
        paginas = []
        for page in doc:
            t = page.get_text("text").strip()
            if t:
                paginas.append(t)
        doc.close()
        return "\n\n".join(paginas)

    if ext == ".docx":
        doc = Document(str(ruta_archivo))
        parrafos = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        return "\n\n".join(parrafos)

    if ext == ".doc":
        # Intentar vía Word COM en Windows
        txt_temp = ruta_archivo.with_suffix(".temp_doc.txt")
        ps_script = f"""
        $ErrorActionPreference = 'Stop'
        $word = New-Object -ComObject Word.Application
        $word.Visible = $false
        $doc = $word.Documents.Open('{str(ruta_archivo.resolve())}', $false, $true)
        $doc.SaveAs([ref]'{str(txt_temp.resolve())}', [ref]2)
        $doc.Close()
        $word.Quit()
        """
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
                check=True
            )
            if txt_temp.exists():
                contenido = txt_temp.read_text(encoding="utf-8", errors="replace").strip()
                txt_temp.unlink(missing_ok=True)
                return contenido
        except Exception:
            if txt_temp.exists():
                txt_temp.unlink(missing_ok=True)
        return ruta_archivo.read_text(encoding="utf-8", errors="ignore").strip()

    return ""


def _limpiar_markdown_para_voz(md_texto: str) -> str:
    """Convierte una celda Markdown de un Notebook en una oración limpia para ser hablada."""
    lineas = []
    for l in md_texto.splitlines():
        l = re.sub(r"^#+\s*", "", l).strip()
        l = re.sub(r"[*_`~]+", "", l).strip()
        l = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", l)
        if l:
            lineas.append(l)
    return " ".join(lineas)


def _describir_codigo_automatico(codigo: str, num_paso: int) -> str:
    """Genera una explicación técnica sobria y variada sin muletillas repetitivas."""
    lineas = [l.strip() for l in codigo.splitlines() if l.strip() and not l.strip().startswith("#")]
    if not lineas:
        return "Mostramos las siguientes líneas de código."
    primera = lineas[0]
    if primera.startswith(("import ", "from ")):
        return "Importamos las dependencias y módulos requeridos para este componente."
    if primera.startswith("def "):
        m = re.match(r"def\s+([a-zA-Z0-9_]+)", primera)
        nom = m.group(1).replace("_", " ") if m else "principal"
        return f"Definimos la función {nom} y especificamos los parámetros de entrada y retorno."
    if primera.startswith("class "):
        m = re.match(r"class\s+([a-zA-Z0-9_]+)", primera)
        nom = m.group(1) if m else "principal"
        return f"Declaramos la clase {nom} con sus atributos correspondientes."
    if "if __name__" in codigo or "print(" in codigo:
        return "Ejecutamos el bloque principal y verificamos la salida obtenida en terminal."
    if "@app." in codigo or "@router." in codigo:
        return "Configuramos el endpoint y su respectivo método HTTP en el enrutador."
    if "=" in primera and not primera.startswith("for ") and not primera.startswith("while "):
        var_nom = primera.split("=")[0].strip()
        return f"Inicializamos la variable {var_nom} con sus valores iniciales."
    return "Continuamos con la implementación de esta sección del código."


def convertir_ipynb_a_pasos(ruta_ipynb: Path) -> list[dict]:
    """
    Lee un Jupyter Notebook (.ipynb) y transforma cada celda de código en un paso explicado.
    Usa las celdas Markdown previas como locución y las salidas (outputs) de la celda como salida de terminal.
    """
    data = json.loads(ruta_ipynb.read_text(encoding="utf-8", errors="replace"))
    cells = data.get("cells", [])
    pasos = []
    md_acumulado = []

    for cell in cells:
        ctype = cell.get("cell_type")
        source = "".join(cell.get("source", [])) if isinstance(cell.get("source"), list) else str(cell.get("source", ""))
        source = source.strip()
        if not source:
            continue

        if ctype == "markdown":
            limpio = _limpiar_markdown_para_voz(source)
            if limpio:
                md_acumulado.append(limpio)

        elif ctype == "code":
            # Extraer salida de la celda si tiene outputs guardados
            salidas = []
            for out in cell.get("outputs", []):
                if "text" in out:
                    txt_out = "".join(out["text"]) if isinstance(out["text"], list) else str(out["text"])
                    salidas.append(txt_out.strip())
                elif "data" in out and "text/plain" in out["data"]:
                    tp = out["data"]["text/plain"]
                    txt_out = "".join(tp) if isinstance(tp, list) else str(tp)
                    salidas.append(txt_out.strip())

            salida_str = " | ".join(s for s in salidas if s)[:160]
            locucion = " ".join(md_acumulado).strip()
            md_acumulado = []

            if not locucion:
                locucion = _describir_codigo_automatico(source, len(pasos) + 1)

            pasos.append({
                "locucion": locucion,
                "codigo": source,
                "zoom": "terminal" if salida_str else "editor",
                "resaltar": "",
                "terminal": f"In [{len(pasos) + 1}]: ejecutar celda" if salida_str else "",
                "salida": salida_str
            })

    return pasos


def auto_segmentar_py_sin_etiquetas(contenido: str, nombre_archivo: str, cantidad_pasos_deseada: int | None = None) -> list[dict]:
    """
    Divide un archivo .py en pasos para tipear en vivo:
    1. Si el archivo tiene marcas explícitas como '# [PASO 1]', '# PASO 1' o '# ---', corta exactamente ahí.
    2. Si no tiene marcas, agrupa por bloques lógicos (funciones, clases, bloques separados por renglón en blanco).
    """
    # 1. Revisar si el usuario puso separadores explícitos (# [PASO 1], # PASO 2, # ---)
    patron_paso = r"(?:^|\n)\s*#\s*(?:\[?\s*PASO\s*\d+\s*[:\-\]]?.*|---+\s*)(?=\n)"
    if re.search(patron_paso, contenido, flags=re.IGNORECASE):
        partes_explicitas = [b.strip("\r\n") for b in re.split(patron_paso, contenido, flags=re.IGNORECASE) if b.strip()]
        bloques_agrupados = partes_explicitas
    else:
        fragmentos = [b.strip("\r\n") for b in re.split(r"\n\s*\n", contenido.strip()) if b.strip()]
        if not fragmentos:
            return []

        if cantidad_pasos_deseada and 0 < cantidad_pasos_deseada < len(fragmentos):
            # Repartir los fragmentos exactamente en la cantidad de párrafos que puso en el guion
            bloques_agrupados = []
            for i in range(cantidad_pasos_deseada):
                ini = int(round((i / cantidad_pasos_deseada) * len(fragmentos)))
                fin = int(round(((i + 1) / cantidad_pasos_deseada) * len(fragmentos)))
                frag_grupo = "\n\n".join(fragmentos[ini:max(ini + 1, fin)])
                if frag_grupo:
                    bloques_agrupados.append(frag_grupo)
        else:
            bloques_agrupados = []
            actual = []
            lineas_actual = 0
            for frag in fragmentos:
                n_l = len(frag.splitlines())
                if actual and (lineas_actual + n_l > 12 or frag.lstrip().startswith(("def ", "class ", "if __name__"))):
                    bloques_agrupados.append("\n\n".join(actual))
                    actual = [frag]
                    lineas_actual = n_l
                else:
                    actual.append(frag)
                    lineas_actual += n_l
            if actual:
                bloques_agrupados.append("\n\n".join(actual))

    pasos = []
    for i, cod in enumerate(bloques_agrupados, start=1):
        # Si el bloque empieza con comentarios normales, usarlos como pista para la locución
        lineas = cod.splitlines()
        comentarios_ini = []
        resto_codigo = []
        en_cabecera = True
        for l in lineas:
            l_str = l.strip()
            # Ignorar si es un comentario en HTML: <!-- ... -->
            if en_cabecera and (l_str.startswith("#") or (l_str.startswith("<!--") and l_str.endswith("-->"))) and "[EXPLICAR:" not in l_str:
                c_txt = re.sub(r"^#+\s*|^<!--\s*|\s*-->$", "", l_str).strip()
                # Filtrar comentarios de metadata interna como 'CLIP 1:', 'CLIP 2...', etc.
                c_limpio = re.sub(r"^clips?\s*\d+[^:.]*[:.]\s*", "", c_txt, flags=re.IGNORECASE).strip()
                if c_limpio and not c_limpio.lower().startswith("clip"):
                    comentarios_ini.append(c_limpio)
            else:
                en_cabecera = False
                resto_codigo.append(l)

        cod_limpio = "\n".join(resto_codigo).strip() or cod
        locucion = " ".join(comentarios_ini) if comentarios_ini else _describir_codigo_automatico(cod_limpio, i)

        es_ultimo = (i == len(bloques_agrupados)) and ("print(" in cod_limpio or "if __name__" in cod_limpio)
        pasos.append({
            "locucion": locucion,
            "codigo": cod_limpio,
            "zoom": "terminal" if es_ultimo else "editor",
            "resaltar": "",
            "terminal": f"python {nombre_archivo}" if es_ultimo else "",
            "salida": ""
        })

    return pasos


def _palabras_clave(texto: str) -> set[str]:
    stop = {
        "el", "la", "los", "las", "un", "una", "de", "del", "en", "con", "por", "para",
        "que", "se", "es", "son", "como", "más", "mas", "pero", "este", "esta", "estos",
        "slide", "diapositiva", "imagen", "clase", "vamos", "ver", "acá", "aca", "entonces"
    }
    return {w for w in re.findall(r"[a-záéíóúüñ0-9]{3,}", (texto or "").lower()) if w not in stop}


def parsear_guion_estructurado(
    guion_texto: str,
    slides: list[str],
    archivos_codigo: list[str]
) -> tuple[list[dict], dict[str, list[str]]] | None:
    """
    Si el documento de guion usa etiquetas explícitas como:
      [SLIDE 1] o SLIDE 1: o 'Bueno, entonces [SLIDE 1]'
      [CODIGO: backend/tareas.py] o CODIGO: tareas.py
    Devuelve la lista exacta de bloques en ese orden y las locuciones de código si se incluyeron.
    """
    patron_encabezado = re.compile(
        r"(?:\[\s*(SLIDE|DIAPOSITIVA|CODIGO|CÓDIGO)\s*[:\-]?\s*([^\]]*?)\s*\]|^\s*(SLIDE|DIAPOSITIVA|CODIGO|CÓDIGO)\s+(\d+|[^\n:]+)\s*:)",
        re.IGNORECASE | re.MULTILINE
    )
    coincidencias = list(patron_encabezado.finditer(guion_texto or ""))
    if not coincidencias:
        return None

    bloques = []
    locuciones_codigo = {}

    for i, match in enumerate(coincidencias):
        tipo_raw = (match.group(1) or match.group(3) or "").upper()
        arg_raw = (match.group(2) or match.group(4) or "").strip()

        inicio_texto = match.end()
        fin_texto = coincidencias[i + 1].start() if (i + 1) < len(coincidencias) else len(guion_texto)
        cuerpo = guion_texto[inicio_texto:fin_texto].strip()
        # Limpiar posibles conectores residuales al final del bloque antes del siguiente tag
        cuerpo = re.sub(r"(?:Bueno|Entonces|O sea|Fíjense que|Básicamente|Y acá lo que vamos a ver es que),?\s*$", "", cuerpo, flags=re.IGNORECASE).strip()

        if tipo_raw in ("SLIDE", "DIAPOSITIVA"):
            archivo_slide = ""
            if arg_raw.isdigit():
                idx_s = int(arg_raw) - 1
                if 0 <= idx_s < len(slides):
                    archivo_slide = slides[idx_s]
            else:
                for s in slides:
                    if arg_raw.lower() in s.lower():
                        archivo_slide = s
                        break
            if not archivo_slide and slides:
                archivo_slide = slides[min(len(bloques), len(slides) - 1)]

            bloques.append({
                "tipo": "slide",
                "archivo": archivo_slide,
                "locucion": cuerpo
            })

        elif tipo_raw in ("CODIGO", "CÓDIGO"):
            archivo_cod = arg_raw.replace("\\", "/")
            # Normalizar para buscar en la lista de codigos disponibles
            for c in archivos_codigo:
                c_norm = c.replace("\\", "/").lower()
                a_norm = archivo_cod.lower()
                if c_norm == a_norm or c_norm.endswith("/" + a_norm) or Path(c).name.lower() == Path(archivo_cod).name.lower():
                    archivo_cod = c
                    break

            bloques.append({
                "tipo": "codigo_anotado",
                "archivo": archivo_cod
            })

            if cuerpo:
                parrafos_cod = [p.strip() for p in re.split(r"\n\s*\n", cuerpo) if p.strip()]
                if parrafos_cod:
                    locuciones_codigo[archivo_cod] = parrafos_cod

    return bloques, locuciones_codigo


def emparejar_guion_con_slides_y_codigo(
    guion_texto: str,
    slides: list[str],
    textos_slides: dict[str, str],
    archivos_codigo: list[str]
) -> list[dict]:
    """
    Cruza automáticamente el guion con las slides y los archivos de código:
    1. Si el guion tiene marcas explícitas (ej: 'Slide 1:', '[Slide 2]', '[Código]'), las respeta.
    2. Si el guion es texto corrido (sin marcas), compara las palabras clave del texto dentro de cada slide
       (y del nombre del archivo) con los párrafos del guion, e intercala el código donde el guion habla de programar/código
       o entre los bloques correspondientes.
    """
    if not slides and not archivos_codigo:
        return []

    estructurado = parsear_guion_estructurado(guion_texto, slides, archivos_codigo)
    if estructurado is not None:
        bloques_est, _ = estructurado
        return bloques_est

    parrafos = [p.strip() for p in re.split(r"\n\s*\n", (guion_texto or "").strip()) if p.strip()]
    if not parrafos:
        bloques = [{"tipo": "slide", "archivo": s, "locucion": f"Explicación de {s}."} for s in slides]
        for c in archivos_codigo:
            bloques.append({"tipo": "codigo_anotado", "archivo": c})
        return bloques

    # Limpiar posibles prefijos "Slide 1:", "Diapositiva 2 -", etc. de cada párrafo
    parrafos_limpios = [
        re.sub(r"^(?:\[?\s*(?:slide|diapositiva|página|pagina)\s*\d+\s*\]?\s*[:\-–]?\s*)", "", p, flags=re.IGNORECASE).strip()
        for p in parrafos
    ]

    bloques_slides = []
    n_slides = len(slides)
    n_parrafos = len(parrafos_limpios)

    if n_slides > 0:
        if n_parrafos == n_slides:
            # Caso 1 a 1 directo
            for s, p in zip(slides, parrafos_limpios):
                bloques_slides.append({"tipo": "slide", "archivo": s, "locucion": p})
        elif n_parrafos > n_slides:
            # Agrupar párrafos contiguos evaluando similitud con el contenido de cada slide
            kws_slides = []
            for s in slides:
                meta_txt = textos_slides.get(s, "") + " " + s.replace("_", " ").replace(".png", "")
                kws_slides.append(_palabras_clave(meta_txt))

            asignacion = [[] for _ in range(n_slides)]
            for idx_p, p in enumerate(parrafos_limpios):
                kws_p = _palabras_clave(p)
                # Posición proporcional esperada para mantener el orden cronológico de la clase
                slide_esperada = min(n_slides - 1, int((idx_p / n_parrafos) * n_slides))
                mejor_s = slide_esperada
                mejor_score = -1.0
                for cand in range(max(0, slide_esperada - 1), min(n_slides, slide_esperada + 2)):
                    inter = len(kws_p & kws_slides[cand])
                    cercania = 1.0 - (abs(cand - slide_esperada) * 0.35)
                    score = inter * 2.0 + cercania
                    if score > mejor_score:
                        mejor_score = score
                        mejor_s = cand
                asignacion[mejor_s].append(p)

            # Garantizar que ninguna slide quede vacía
            for i in range(n_slides):
                if not asignacion[i]:
                    asignacion[i].append(parrafos_limpios[min(i, n_parrafos - 1)])
                bloques_slides.append({
                    "tipo": "slide",
                    "archivo": slides[i],
                    "locucion": " ".join(asignacion[i])
                })
        else:
            # Hay menos párrafos que slides: dividir por oraciones para cubrir todas las slides
            oraciones = [o.strip() for o in re.split(r"(?<=[.?!])\s+", " ".join(parrafos_limpios)) if o.strip()]
            for i, s in enumerate(slides):
                inicio = int((i / n_slides) * len(oraciones))
                fin = max(inicio + 1, int(((i + 1) / n_slides) * len(oraciones)))
                frag = " ".join(oraciones[inicio:fin]) or f"Explicación de la diapositiva {i + 1}."
                bloques_slides.append({"tipo": "slide", "archivo": s, "locucion": frag})

    # Intercalar archivos de código donde el guion mencione código/ejemplo o distribuirlos
    if not archivos_codigo:
        return bloques_slides

    codigos_pendientes = list(archivos_codigo)
    resultado = []
    palabras_trigger_codigo = {"código", "codigo", "python", "script", "función", "funcion", "notebook", "programar", "consola", "terminal", "ejemplo"}

    for idx, b in enumerate(bloques_slides):
        resultado.append(b)
        if codigos_pendientes:
            kws_loc = _palabras_clave(b["locucion"])
            # Si menciona el nombre del archivo o palabras de código, o estamos en la mitad de la clase
            nombre_cod_sin_ext = Path(codigos_pendientes[0]).stem.lower()
            if (nombre_cod_sin_ext in b["locucion"].lower()) or (kws_loc & palabras_trigger_codigo) or (idx == max(0, len(bloques_slides) // 2 - 1)):
                resultado.append({"tipo": "codigo_anotado", "archivo": codigos_pendientes.pop(0)})

    while codigos_pendientes:
        resultado.append({"tipo": "codigo_anotado", "archivo": codigos_pendientes.pop(0)})

    return resultado

