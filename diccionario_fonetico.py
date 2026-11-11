import re
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
RUTA_DICCIONARIO = BASE_DIR / "diccionario_fonetico.json"

# Diccionario técnico predefinido adaptado a pronunciación natural para TTS en español
DICCIONARIO_BASE = {
    # Arquitectura & Conceptos Web
    "backend": "bákend",
    "backends": "bákends",
    "frontend": "fróntend",
    "frontends": "fróntends",
    "fullstack": "fulsták",
    "framework": "fréimwork",
    "frameworks": "fréimworks",
    "endpoint": "éndpoint",
    "endpoints": "éndpoints",
    "browser": "bráuser",
    "browsers": "bráusers",
    "middleware": "mídeluer",
    "middlewares": "mídeluers",
    "deploy": "deplói",
    "deployar": "deploiár",
    "token": "tóken",
    "tokens": "tókens",
    "payload": "péiloud",
    "payloads": "péilouds",
    "default": "difólt",
    "setup": "set-áp",
    "loop": "lup",
    "loops": "lups",
    "debug": "dibág",
    "debugger": "dibáguer",
    "debugging": "dibággin",
    "callback": "cólbak",
    "callbacks": "cólbaks",
    "router": "ráuter",
    "routers": "ráuters",
    "route": "raut",
    "routes": "rauts",
    "cookie": "kúki",
    "cookies": "kúkis",
    "cache": "cash",
    "caching": "cáshin",
    "session": "sésion",
    "sessions": "sésions",
    "buffer": "báfer",
    "buffers": "báfers",
    "thread": "thred",
    "threads": "threds",
    "socket": "sóket",
    "sockets": "sókets",
    "websocket": "uéb-sóket",
    "websockets": "uéb-sókets",
    "serverless": "sérver-les",
    "cloud": "cláud",
    "host": "jost",
    "localhost": "lócal-jost",

    # Frameworks y Herramientas Populares
    "fastapi": "Fast-ei-pi-ai",
    "flask": "flask",
    "uvicorn": "iúvicorn",
    "pydantic": "paidántik",
    "basemodel": "beis-módel",
    "gradio": "grádio",
    "streamlit": "strímlit",
    "github": "gít-jab",
    "gitlab": "gít-lab",
    "docker": "dóker",
    "kubernetes": "kubernétis",
    "sqlite": "ese-cu-ele láit",
    "sql": "ese-cu-ele",
    "nosql": "nou-ese-cu-ele",
    "postgresql": "póstgres",
    "postgres": "póstgres",
    "mongodb": "móngo-de-be",
    "node": "noud",
    "nodejs": "noud-yei-ese",
    "npm": "ene-pe-eme",
    "pip": "pip",
    "pytest": "pai-test",
    "jupyter": "yúpiter",

    # Siglas Técnicas y Lenguajes
    "api": "ei-pi-ai",
    "apis": "ei-pi-ais",
    "json": "yeison",
    "html": "hache-te-eme-ele",
    "css": "ce-ese-ese",
    "javascript": "yáva-script",
    "typescript": "táip-script",
    "python": "páiton",
    "wsgi": "uásgui",
    "asgi": "ásgui",
    "crud": "crud",
    "rest": "rest",
    "restful": "réstful",

    # Términos de Código, Git y Red
    "script": "escrípt",
    "scripts": "escrípts",
    "repo": "répo",
    "repos": "répos",
    "commit": "comít",
    "commits": "comíts",
    "branch": "branch",
    "branches": "bránches",
    "pull request": "pul rikuést",
    "pull requests": "pul rikuésts",
    "merge": "merch",
    "fetch": "fech",
    "file": "fáil",
    "request": "rikuést",
    "requests": "rikuésts",
    "response": "respóns",
    "responses": "respónses",
    "post": "post",
    "patch": "patch",
    "get": "guet",
    "delete": "delít",
    "query": "kuéri",
    "queries": "kuéris",
    "body": "bódi",
    "header": "jéder",
    "headers": "jéders",
    "async": "asínc",
    "await": "agueit",
    "try": "trai",
    "catch": "catch",
    "null": "nal",
    "undefined": "andifáind",
    "array": "arréi",
    "arrays": "arréis",
    "string": "string",
    "strings": "strings",
    "boolean": "bulean",
    "booleans": "buleans"
}


def cargar_diccionario() -> dict:
    dic = dict(DICCIONARIO_BASE)
    if RUTA_DICCIONARIO.exists():
        try:
            custom = json.loads(RUTA_DICCIONARIO.read_text(encoding="utf-8"))
            dic.update(custom)
        except Exception:
            pass
    return dic


def guardar_diccionario(dic: dict):
    RUTA_DICCIONARIO.write_text(json.dumps(dic, ensure_ascii=False, indent=2), encoding="utf-8")


def aplicar_fonetica(texto: str, usar_diccionario_automatico: bool = True) -> str:
    """
    Aplica fonética adaptada para que las voces TTS lean el inglés de forma clara y natural en español.
    
    Prioridad:
    1. Marcas manuales escritas por el usuario en el texto:
       - {palabra|cómo leerla}       -> Ej: {backend|bákend}, {file|fáil}, {FastAPI|Fast ei pi ai}
       - [leer: palabra -> lectura]   -> Ej: [leer: backend -> bákend]
       - [en: palabra]                -> Ej: [en: frontend] (usa el diccionario fonético)
    2. Diccionario fonético técnico automático (si está activado).
    """
    if not texto:
        return ""

    # 0. Soporte completo para XML / SSML en guiones:
    # Si el usuario escribe etiquetas de pronunciación XML como:
    #   <sub alias="fáil">file</sub>  -> se extrae el alias "fáil"
    #   <break time="1s" />            -> se convierte en pausas elípticas "..."
    #   <speak>...</speak>, <voice>..</voice>, <prosody>...</prosody> -> se extrae su contenido limpio
    texto = re.sub(r'<sub\s+alias=["\'](.*?)["\']\s*>(?:.*?)<\/sub>', r' \1 ', texto, flags=re.IGNORECASE)
    texto = re.sub(r'<break\s+time=["\'](?:\d+(?:\.\d+)?(?:s|ms))?["\']\s*\/?>', r' ... ', texto, flags=re.IGNORECASE)
    texto = re.sub(r'<\/?(?:speak|voice|prosody|emphasis|say-as|phoneme)(?:\s+[^>]*?)?>', r' ', texto, flags=re.IGNORECASE)

    # 1. Marcas manuales exactas del usuario: {palabra|lectura}
    texto = re.sub(r"\{\s*([^|}]+?)\s*\|\s*([^}]+?)\s*\}", r"\2", texto)

    # Marcas manuales con flecha: [leer: palabra -> lectura] o [pron: palabra = lectura]
    texto = re.sub(r"\[(?:leer|pron):\s*([^->=]+?)\s*(?:->|=)\s*([^\]]+?)\s*\]", r"\2", texto, flags=re.IGNORECASE)

    dic = cargar_diccionario() if usar_diccionario_automatico else {}

    # Marca rápida de inglés: [en: palabra]
    def _reemplazar_en(match):
        pal = match.group(1).strip()
        return dic.get(pal.lower(), pal)

    texto = re.sub(r"\[en:\s*([^\]]+?)\s*\]", _reemplazar_en, texto, flags=re.IGNORECASE)

    # 2. Reemplazo automático de términos técnicos por límites de palabra
    if usar_diccionario_automatico and dic:
        # Ordenar por longitud descendente para que 'pull request' no sea capturado por 'request'
        claves_ordenadas = sorted(dic.keys(), key=len, reverse=True)
        for k in claves_ordenadas:
            v = dic[k]
            patron = rf"(?<![\w\-])\b{re.escape(k)}\b(?![\w\-])"
            texto = re.sub(patron, v, texto, flags=re.IGNORECASE)

    return texto


def aplicar_seseo_latino(texto: str) -> str:
    """
    Convierte 'z' y 'c' suave (ce, ci) a 's' para neutralizar el acento y ceceo
    español peninsular en modelos como XTTS-v2 que fueron entrenados en España.
    
    Ejemplos:
      - 'hacer' -> 'haser'
      - 'gracias' -> 'grasias'
      - 'empezar' -> 'empesar'
      - 'dice' -> 'dise'
      - 'vez' -> 'ves'
    """
    if not texto:
        return ""

    # 1. 'z' o 'Z' siempre a 's' o 'S' (en español rioplatense/latino z suena siempre como s)
    t = re.sub(r"z", "s", texto)
    t = re.sub(r"Z", "S", t)

    # 2. 'c' o 'C' ante 'e', 'i', 'é', 'í' -> 's' / 'S'
    # Cuidado: no tocar 'ch' ni 'ca, co, cu, cl, cr'
    t = re.sub(r"c(?=[eéií])", "s", t)
    t = re.sub(r"C(?=[eéií])", "S", t)
    t = re.sub(r"c(?=[EÉIÍ])", "s", t)
    t = re.sub(r"C(?=[EÉIÍ])", "S", t)

    return t

