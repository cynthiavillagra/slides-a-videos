"""
================================================================================
GUÍA DE ANOTACIONES PARA EL TIPEADOR DE CÓDIGO (VS CODE ANIMADO)
================================================================================

Este archivo sirve como plantilla y ejemplo de TODAS las anotaciones que podés 
usar para que el motor tipee código en vivo, mueva la cámara, resalte líneas 
y ejecute comandos en la terminal integrada.

SINTAXIS GENERAL DE UNA ANOTACIÓN:
# Formato: [EXPLICAR: locución | ZOOM: zona | RESALTAR: desde-hasta | TERMINAL: comando | SALIDA: texto]

PARÁMETROS SOPORTADOS:
1. EXPLICAR (Obligatorio en cada paso):
   - Es lo que la voz de la IA narrará mientras tipea este fragmento de código.
   - Podés usar fonética manual: {palabra|cómo leerla} (ej: {FastAPI|Fast ei pi ai}, {file|fáil}).
   - Podés usar marcas XML/SSML: <sub alias="erréy">array</sub> o pausas <break time="800ms" />.
   - Los términos técnicos comunes (JSON, backend, frontend, pip...) se leen bien solos.

2. ZOOM (Opcional):
   - editor   -> Acerca la cámara a la zona donde se tipea el código.
   - terminal -> Acerca la cámara hacia el panel inferior de la terminal.
   - sidebar  -> Acerca la cámara al explorador de archivos izquierdo.
   - reset    -> Vuelve a la vista normal completa de la ventana de VS Code.

3. RESALTAR (Opcional):
   - Formato: desde-hasta (número de líneas, ej: 1-3, 5-8).
   - Las líneas indicadas brillan con borde azul de VS Code y el resto se atenúa al 25%
     para enfocar la atención del espectador exactamente en esa sección.

4. TERMINAL (Opcional):
   - Escribe y simula ejecutar un comando en la consola de PowerShell / Bash.
   - Ej: TERMINAL: python main.py, uvicorn app:app --reload, pytest

5. SALIDA (Opcional):
   - Texto que aparece como resultado debajo del comando en la terminal.
   - Admite etiquetas HTML como <span style="color:#22c55e;">[OK]</span> o saltos <br>.
================================================================================
"""

# [EXPLICAR: Arrancamos con las importaciones necesarias. Traemos {FastAPI|Fast ei pi ai} y el modelo base de {Pydantic|paidántik}. | ZOOM: editor]
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional


# [EXPLICAR: Ahora definimos la estructura de datos usando una clase de {Pydantic|paidántik} para validar las tareas. | ZOOM: editor | RESALTAR: 1-4]
class Tarea(BaseModel):
    id: int
    titulo: str
    completada: bool = False
    prioridad: Optional[str] = "media"


# [EXPLICAR: Creamos la instancia principal de la aplicación y una lista en memoria que simulará nuestra base de datos. | ZOOM: editor]
app = FastAPI(title="API de Tareas")

DB_TAREAS: List[dict] = [
    {"id": 1, "titulo": "Subir el ticket de salida", "completada": False, "prioridad": "alta"},
    {"id": 2, "titulo": "Revisar la documentación", "completada": True, "prioridad": "baja"},
]


# [EXPLICAR: Configuramos el primer {endpoint|éndpoint} con el método {GET|guet} para obtener todas las tareas en formato {JSON|yeison}. | ZOOM: editor | RESALTAR: 1-3]
@app.get("/api/tareas", response_model=List[Tarea])
def listar_tareas():
    return DB_TAREAS


# [EXPLICAR: Creamos un {endpoint|éndpoint} con método {POST|poust} para agregar una nueva tarea validando el cuerpo del pedido. | ZOOM: editor]
@app.post("/api/tareas", status_code=201)
def crear_tarea(tarea: Tarea):
    DB_TAREAS.append(tarea.dict())
    return {"mensaje": "Tarea creada exitosamente", "tarea": tarea}


# [EXPLICAR: Y para probar la aplicación, ejecutamos el servidor con {uvicorn|iúvicorn} directamente en la terminal. | ZOOM: terminal | TERMINAL: uvicorn main:app --reload | SALIDA: INFO: Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)<br>INFO: Application startup complete.]
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
