import re
import json
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
RUTA_MODELO_LOCAL = BASE_DIR / "estilo_habla_modelo.json"
RUTA_MODELO_EXTRAER_AUDIO = BASE_DIR.parent / "extraer-audio" / "estilo_habla_modelo.json"

STOPWORDS_ES = {
    "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "al", "a",
    "en", "con", "por", "para", "sin", "sobre", "entre", "hasta", "desde", "que",
    "y", "e", "o", "u", "pero", "sino", "como", "cuando", "donde", "quien", "cual",
    "se", "me", "te", "le", "nos", "les", "lo", "su", "sus", "mi", "mis", "tu", "tus",
    "es", "son", "fue", "era", "ser", "esta", "estan", "este", "esta", "estos", "estas",
    "eso", "esa", "ese", "esos", "esas", "aquel", "todo", "toda", "todos", "todas",
    "mas", "menos", "muy", "ya", "no", "si", "tambien", "solo", "porque", "pues",
    "hay", "tiene", "tienen", "hacer", "hace", "puede", "pueden", "ir", "va", "van"
}

REEMPLAZOS_BASE_ESTILO = [
    (r"\ba continuación veremos\b", "ahora vamos a ver"),
    (r"\ba continuación\b", "ahora"),
    (r"\bes importante destacar que\b", "fíjense que"),
    (r"\bes importante mencionar que\b", "tengan en cuenta que"),
    (r"\bcabe destacar que\b", "fíjense que"),
    (r"\bdebemos considerar\b", "tenemos que tener en cuenta"),
    (r"\bdebemos\b", "tenemos que"),
    (r"\bdebes\b", "tenés que"),
    (r"\bpuedes\b", "podés"),
    (r"\btienes\b", "tenés"),
    (r"\bquieres\b", "querés"),
    (r"\bsabes\b", "sabés"),
    (r"\bhaces\b", "hacés"),
    (r"\bpones\b", "ponés"),
    (r"\bobserva\b", "fijate"),
    (r"\bobserven\b", "fíjense"),
    (r"\bmira\b", "mirá"),
    (r"\bpiensa\b", "pensá"),
    (r"\brecuerda\b", "acordate"),
    (r"\butilizaremos\b", "vamos a usar"),
    (r"\butilizar\b", "usar"),
    (r"\brealizaremos\b", "vamos a hacer"),
    (r"\bcrearemos\b", "vamos a crear"),
    (r"\bveremos\b", "vamos a ver"),
    (r"\banalizaremos\b", "vamos a analizar"),
    (r"\bdefiniremos\b", "vamos a definir"),
    (r"\bimplementaremos\b", "vamos a implementar"),
    (r"\btendremos\b", "vamos a tener"),
    (r"\btendrán\b", "van a tener"),
    (r"\bpodrán\b", "van a poder"),
    (r"\baquí\b", "acá"),
    (r"\bmuchísimos\b", "un montón de"),
    (r"\bmuchas cosas\b", "un montón de cosas"),
    (r"\bpor consiguiente\b", "entonces"),
    (r"\bpor lo tanto\b", "así que"),
    (r"\bsin embargo\b", "pero"),
    (r"\bno obstante\b", "igual"),
    (r"\bes decir\b", "o sea"),
    (r"\ben conclusión\b", "en resumen"),
    (r"\bfinalmente\b", "y por último"),
]


from collections import Counter
import numpy as np

PATRONES_MARCADORES_HABLA = [
    "vamos a ver", "vamos a hacer", "vamos a poner", "vamos a crear", "vamos a usar",
    "lo que vamos a", "entonces vamos a", "yo les voy a", "les voy a", "lo voy a",
    "voy a crear", "voy a hacer", "voy a poner", "van a tener", "van a ver",
    "o sea", "por ejemplo", "digamos", "básicamente", "basicamente", "entonces",
    "fíjense que", "fijense que", "fíjense", "fijate que", "fijate", "miren que",
    "vieron que", "acá tenemos", "aca tenemos", "acá", "aca", "un montón de",
    "un monton de", "no sé si", "no se si", "es lo mismo", "dentro de la",
    "a través de", "a traves de", "en este caso", "por otro lado", "de alguna manera",
    "qué pasa si", "que pasa si", "se entiende", "me explico", "está bien", "esta bien",
    "bueno", "claro", "exacto", "joya", "genial", "perfecto", "cuestión que"
]


def entrenar_modelo_estilo_desde_textos(textos_transcripciones: list[str], fuentes: list[str] | None = None) -> dict:
    """
    Entrena un perfil de estilo de habla a partir de transcripciones (.txt, .srt, .vtt, etc.)
    aprendiendo muletillas, conectores, ritmo de palabras por oración y vocabulario distintivo.
    """
    oraciones_limpias = []
    for t in textos_transcripciones:
        # Limpiar marcas de tiempo tipo 00:01:23 o encabezados de hablante tipo 'Speaker 1:'
        limpio = re.sub(r"\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d+)?", "", t)
        limpio = re.sub(r"^[A-Za-z0-9_\s]+:\s*", "", limpio)
        limpio = re.sub(r"\s+", " ", limpio).strip()
        # Separar por frases
        frases = [f.strip() for f in re.split(r"(?<=[.?!])\s+", limpio) if len(f.strip().split()) >= 3]
        oraciones_limpias.extend(frases)

    if not oraciones_limpias:
        raise ValueError("No se encontraron oraciones con contenido suficiente en las transcripciones.")

    texto_completo = " ".join(oraciones_limpias)
    texto_lower = texto_completo.lower()
    palabras_todas = re.findall(r"[a-záéíóúüñ]+", texto_lower)
    total_palabras = max(1, len(palabras_todas))

    longitudes = [len(o.split()) for o in oraciones_limpias]
    long_media = round(float(np.mean(longitudes)), 1)
    long_mediana = round(float(np.median(longitudes)), 1)

    # 1. Contar marcadores discursivos
    marcadores_conteo = {}
    for m in PATRONES_MARCADORES_HABLA:
        c = len(re.findall(r"\b" + re.escape(m) + r"\b", texto_lower))
        if c > 0:
            clave = (
                m.replace("basicamente", "básicamente")
                 .replace("fijense", "fíjense")
                 .replace("aca", "acá")
                 .replace("monton", "montón")
                 .replace("no se si", "no sé si")
                 .replace("a traves de", "a través de")
                 .replace("que pasa si", "qué pasa si")
                 .replace("esta bien", "está bien")
            )
            marcadores_conteo[clave] = marcadores_conteo.get(clave, 0) + c

    top_marcadores = sorted(
        [{"frase": k, "frecuencia": v} for k, v in marcadores_conteo.items()],
        key=lambda x: -x["frecuencia"]
    )[:25]

    # 2. Aperturas y cierres
    aperturas_counter = Counter()
    cierres_counter = Counter()
    for o in oraciones_limpias:
        toks = re.findall(r"[a-záéíóúüñ]+", o.lower())
        if len(toks) >= 4:
            ap = " ".join(toks[:2])
            if ap in ("bueno", "entonces", "ahora", "fíjense", "fijate", "digamos", "básicamente", "acá", "por ejemplo", "o sea"):
                aperturas_counter[ap.capitalize()] += 1
            ci = " ".join(toks[-2:])
            if ci in ("se entiende", "está bien", "esta bien", "o no", "por ejemplo"):
                cierres_counter[ci] += 1

    aperturas_tipicas = [k for k, _ in aperturas_counter.most_common(8)] or ["Bueno, entonces", "Fíjense que", "Ahora vamos a ver"]
    cierres_tipicos = [k for k, _ in cierres_counter.most_common(6)] or ["está bien", "se entiende"]

    # 3. Muletillas personalizadas más fuertes
    muletillas_custom = [m["frase"] for m in top_marcadores[:10]] or ["bueno", "acá", "entonces", "o sea", "por ejemplo", "vamos a ver", "fíjense"]

    # 4. Bloques RAG para transferir estilo
    bloques_rag = []
    buf = []
    buf_words = 0
    for o in oraciones_limpias:
        buf.append(o)
        buf_words += len(o.split())
        if buf_words >= 30:
            b_txt = " ".join(buf)
            kws = list(set(w for w in re.findall(r"[a-záéíóúüñ]{4,}", b_txt.lower()) if w not in STOPWORDS_ES))
            bloques_rag.append({"texto": b_txt, "keywords": kws[:25]})
            buf = []
            buf_words = 0

    modelo = {
        "entrenado": True,
        "fecha_entrenamiento": json.dumps({"t": ""})[6:16],
        "fuentes": fuentes or ["Transcripción de usuario"],
        "metricas": {
            "total_intervenciones": len(oraciones_limpias),
            "total_palabras": total_palabras,
            "palabras_por_oracion_media": long_media,
            "palabras_por_oracion_mediana": long_mediana,
            "palabras_por_minuto": 180.0,
            "total_bloques_rag": len(bloques_rag),
        },
        "top_marcadores": top_marcadores,
        "aperturas_tipicas": aperturas_tipicas,
        "cierres_tipicos": cierres_tipicos,
        "muletillas_personalizadas": muletillas_custom,
        "bloques_rag": bloques_rag[:200],
    }

    RUTA_MODELO_LOCAL.write_text(json.dumps(modelo, ensure_ascii=False, indent=2), encoding="utf-8")
    return modelo


def cargar_modelo_estilo() -> dict:
    rutas = []
    if RUTA_MODELO_EXTRAER_AUDIO.exists():
        rutas.append(RUTA_MODELO_EXTRAER_AUDIO)
    if RUTA_MODELO_LOCAL.exists():
        rutas.append(RUTA_MODELO_LOCAL)
    if not rutas:
        return {"entrenado": False}

    # Usar el más reciente si están ambos
    ruta_elegida = max(rutas, key=lambda p: p.stat().st_mtime)
    try:
        return json.loads(ruta_elegida.read_text(encoding="utf-8"))
    except Exception:
        return {"entrenado": False}


def recuperar_ejemplos_similares_rag(texto_consulta: str, modelo: dict, top_k: int = 3) -> list[str]:
    bloques = modelo.get("bloques_rag", [])
    if not bloques:
        return []
    kws_q = set(w for w in re.findall(r"[a-záéíóúüñ]{4,}", (texto_consulta or "").lower()) if w not in STOPWORDS_ES)
    puntuados = []
    for idx, b in enumerate(bloques):
        kws_b = set(b.get("keywords", []))
        inter = len(kws_q & kws_b)
        txt_b = b.get("texto", "")
        bonus = sum(0.35 for m in modelo.get("muletillas_personalizadas", [])[:8] if m.lower() in txt_b.lower())
        score = inter * 2.0 + bonus
        puntuados.append((score, idx, txt_b))
    puntuados.sort(key=lambda x: (-x[0], x[1]))
    return [x[2] for x in puntuados[:top_k]]


def _adaptar_oracion(oracion: str, idx_oracion: int, total_oraciones: int,
                     intensidad: str, muletillas: list[str], cierres: list[str]) -> str:
    txt = oracion.strip()
    if not txt:
        return ""

    for patron, reemplazo in REEMPLAZOS_BASE_ESTILO:
        def _repl(match):
            orig = match.group(0)
            if orig[0].isupper():
                return reemplazo[0].upper() + reemplazo[1:]
            return reemplazo
        txt = re.sub(patron, _repl, txt, flags=re.IGNORECASE)

    if ";" in txt:
        partes_pc = [p.strip() for p in txt.split(";") if p.strip()]
        if len(partes_pc) > 1:
            txt = ". ".join(p[0].upper() + p[1:] if p else "" for p in partes_pc)

    ya_empieza_oral = any(
        txt.lower().startswith(pref)
        for pref in ("bueno", "entonces", "ahora", "fíjense", "fijate", "mirá", "o sea", "acá", "básicamente", "vamos a")
    )

    if not ya_empieza_oral and len(txt.split()) >= 5:
        if idx_oracion == 0 and intensidad in ("equilibrado", "conversacional"):
            ap = "Bueno, hoy vamos a ver " if txt.lower().startswith(("el ", "la ", "los ", "las ")) and intensidad == "conversacional" else "Bueno, entonces "
            txt = ap + txt[0].lower() + txt[1:]
        elif idx_oracion > 0:
            if intensidad == "conversacional" and idx_oracion % 2 == 1:
                conectores = [
                    "Entonces, ",
                    "Fíjense que ",
                    "Y acá lo que vamos a ver es que ",
                    "O sea, ",
                    "Básicamente, ",
                ]
                elegido = conectores[idx_oracion % len(conectores)]
                txt = elegido + txt[0].lower() + txt[1:]
            elif intensidad == "equilibrado" and idx_oracion % 3 == 1:
                conectores_eq = ["Entonces, ", "Fíjense que ", "O sea, ", "Además, acá "]
                elegido = conectores_eq[idx_oracion % len(conectores_eq)]
                txt = elegido + txt[0].lower() + txt[1:]

    if intensidad in ("equilibrado", "conversacional") and "por ejemplo" not in txt.lower():
        txt = re.sub(r",\s*como puede ser\b", ", por ejemplo,", txt, flags=re.IGNORECASE)
        txt = re.sub(r"\btales como\b", "como por ejemplo", txt, flags=re.IGNORECASE)

    if intensidad == "conversacional" and idx_oracion == total_oraciones - 1 and not txt.endswith("?"):
        if not txt.endswith("."):
            txt += "."
        cierre_add = " ¿Se entiende la idea?" if "se entiende" in " ".join(cierres).lower() else " ¿Está bien?"
        txt = txt + cierre_add

    return txt


def adaptar_texto_a_mi_estilo(texto_original: str, intensidad: str = "conversacional", usar_ollama: bool = False) -> dict:
    """
    Convierte un guion o locución al estilo personal entrenado en estilo_habla_modelo.json.
    """
    texto_original = (texto_original or "").strip()
    if not texto_original:
        return {"texto_convertido": "", "modelo_activo": False}

    modelo = cargar_modelo_estilo()
    muletillas = modelo.get("muletillas_personalizadas") or ["acá", "entonces", "bueno", "por ejemplo", "vamos a ver", "o sea"]
    cierres = modelo.get("cierres_tipicos") or ["está bien", "se entiende"]
    ejemplos_rag = recuperar_ejemplos_similares_rag(texto_original, modelo, top_k=3)

    if usar_ollama:
        top_m_str = ", ".join(f'"{m}"' for m in muletillas[:10])
        ejemplos_str = "\n".join(f'- "{ej}"' for ej in ejemplos_rag)
        prompt_adn = (
            "Sos un clon exacto de mi forma de hablar dando clases en español rioplatense (Argentina).\n"
            f"Expresiones reales que más uso al explicar: {top_m_str}.\n"
            "Uso voseo natural (fíjense, acá, entonces, o sea, vamos a ver, les voy a mostrar, un montón de).\n"
            f"Ejemplos reales de mis clases:\n{ejemplos_str}\n\n"
            "Reescribí el siguiente texto para que suene 100% dicho por mí en clase, manteniendo cada párrafo separado por una línea en blanco:\n\n"
            f"{texto_original}"
        )
        try:
            req_data = json.dumps({"model": "llama3", "prompt": prompt_adn, "stream": False}).encode("utf-8")
            req = urllib.request.Request(
                "http://127.0.0.1:11434/api/generate",
                data=req_data,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                r_json = json.loads(resp.read().decode("utf-8"))
                resp_txt = (r_json.get("response") or "").strip()
                if resp_txt:
                    return {
                        "texto_convertido": resp_txt,
                        "modelo_activo": bool(modelo.get("entrenado")),
                        "metricas": modelo.get("metricas", {}),
                        "muletillas": muletillas
                    }
        except Exception:
            pass

    parrafos = [p.strip() for p in re.split(r"\n\s*\n", texto_original) if p.strip()]
    parrafos_convertidos = []
    idx_global = 0
    total_oraciones_est = sum(len(re.split(r"(?<=[.?!])\s+", p)) for p in parrafos)

    for parrafo in parrafos:
        oraciones = [o.strip() for o in re.split(r"(?<=[.?!])\s+", parrafo) if o.strip()]
        nuevas_oraciones = []
        for o in oraciones:
            adaptada = _adaptar_oracion(
                o, idx_global, max(1, total_oraciones_est),
                intensidad=intensidad,
                muletillas=muletillas,
                cierres=cierres
            )
            if adaptada:
                nuevas_oraciones.append(adaptada)
            idx_global += 1
        parrafos_convertidos.append(" ".join(nuevas_oraciones))

    return {
        "texto_convertido": "\n\n".join(parrafos_convertidos),
        "modelo_activo": bool(modelo.get("entrenado")),
        "metricas": modelo.get("metricas", {}),
        "muletillas": muletillas
    }
