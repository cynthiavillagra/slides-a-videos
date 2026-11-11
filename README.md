# Generador Universal de Videos Técnicos y Tutoriales

Generador automatizado de videos técnicos que combina **diapositivas HD**, **código fuente tipeado en vivo sincronizado** dentro de un simulador visual de Visual Studio Code (con explorador de proyecto, resaltado de sintaxis con alto contraste, terminal y zoom) y **locución neuronal técnica** con soporte fonético y marcas SSML.

---

## 🚀 Inicio Rápido

1. **Clonar o descargar el repositorio:**
   ```bash
   git clone <URL_DEL_REPOSITORIO>
   cd "creador de videos"
   ```

2. **Crear y activar un entorno virtual:**
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

3. **Instalar dependencias y Chromium para Playwright:**
   ```powershell
   pip install -r requirements.txt
   playwright install chromium
   ```

4. **Ejecutar la aplicación web:**
   ```powershell
   python app_web.py
   ```
   Abrí tu navegador en: **http://localhost:8080**

---

## 💡 Características Principales

- **Simulador de Editor VS Code a 60 FPS:** Renderizado en Chromium con Monaco / tema VS Code Dark+ optimizado para alto contraste.
- **Sincronización Exacta Código - Audio:** Tipeo gobernado por `requestAnimationFrame` en el navegador, adaptando la velocidad del tipeo exactamente a la duración del audio narrado.
- **Soporte de Marcas SSML y Diccionario Fonético:**
  - Etiquetas `<sub alias="pronunciacion">termino</sub>` para pronunciación técnica impecable en español (evita que la IA deletree o distorsione palabras en inglés).
  - Pausas temporizadas con `<break time="1.0s"/>`.
  - Normalizador de seseo latinoamericano y velocidad ajustada al `-10%` para máxima claridad pedagógica.
- **Soporte de Múltiples Formatos de Entrada:**
  - Diapositivas: `.pdf`, `.pptx`, imágenes sueltas (`.png`, `.jpg`).
  - Guiones: `.docx`, `.pdf`, `.md`, `.txt` o redacción directa en la interfaz web.
  - Código y Proyectos: Archivos individuales (`.py`, `.js`, etc.), notebooks (`.ipynb`) o carpetas completas de proyecto (`.zip`).
- **Control Total de la Secuencia:** Panel interactivo para previsualizar, reordenar y ajustar cada bloque (diapositivas y código).
- **Estimación de Renderizado en Tiempo Real:** Barra de progreso con cálculo dinámico del tiempo restante durante la compilación final.

---

## 📂 Formato de Guion y Estructura

Podés estructurar tu guion con etiquetas directas para vincular diapositivas y código con precisión:

```text
[SLIDE 1]
Hola a todos. Hoy veremos cómo construir un pipeline de datos en Python.

[SLIDE 2]
En este diagrama podemos observar el flujo entre el cliente y el servidor.

[CODIGO: main.py]
Primero importamos las librerías necesarias y configuramos el cliente.

Ahora definimos la función principal que procesará cada registro en la base de datos.

[SLIDE 3]
Para finalizar, repasemos las conclusiones del módulo.
```

---

## 💻 Anotaciones en el Código Fuente

El generador admite anotaciones especiales dentro de los archivos de código para orquestar la explicación paso a paso. Consultá el archivo de referencia [`ejemplo_anotaciones_tipeador.py`](ejemplo_anotaciones_tipeador.py) para ver todos los modificadores disponibles:

```python
# EXPLICAR: En esta sección definimos la función para calcular totales.
# ZOOM: 120%
# RESALTAR: L2-L4
def calcular_total(productos):
    subtotal = sum(p["precio"] for p in productos)
    return subtotal * 1.21

# TERMINAL: python main.py
# SALIDA: Total calculado: $1210.00
```

---

## 🛠️ Requisitos Técnicos

- **Python 3.10+**
- **FFmpeg:** Instalado en el sistema o provisto automáticamente vía `imageio-ffmpeg`.
- **Playwright Chromium:** Para la captura del canvas y simulación del editor de código.
- **Acceso a Internet (para Edge TTS):** Voces neuronales de alta calidad (`es-MX-JorgeNeural`, `es-MX-DaliaNeural`, etc.).

---

## 📄 Licencia

Distribuido bajo la Licencia MIT. Consultá `LICENSE` para más detalles.
