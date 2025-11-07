"""

- Si el URL parece un archivo de video directo (.mp4/.webm/.ogg/.mov), usa requests y guarda el archivo tal cual.
- Si el URL es de una plataforma (Instagram, YouTube, TikTok), usa yt-dlp para descargar el video.

Por qué estas decisiones:
- Mantener una única vista y una ruta de descarga encaja con los ejemplos de clase (sencillos y claros).
- Validar Content-Type y extensión evita descargar HTML como si fuera .mp4 (archivo corrupto).
- Usar yt-dlp sólo cuando el dominio es de plataforma minimiza dependencias y sorpresas.
- Detectar ffmpeg (del sistema o portátil via imageio-ffmpeg) permite fusionar video+audio y remux a mp4.
  Si no hay ffmpeg, pedimos un stream progresivo único para evitar errores de fusión.
- Saneamos el nombre de archivo para que el enlace /download/<filename> funcione y el sistema acepte el nombre.
- Verificamos tamaño mínimo (100KB) para filtrar descargas vacías o inválidas.

Dependencias principales:
- Flask, requests.
- yt-dlp (pip install yt-dlp) para plataformas.
- imageio-ffmpeg (opcional, pip install imageio-ffmpeg) para disponer de ffmpeg portátil.
"""
from flask import Flask, render_template, request, send_from_directory
import os
import requests
import urllib.parse
import shutil
import re

# yt-dlp: librería especializada para extraer/descargar medios de múltiples plataformas.
# Integramos lo mínimo imprescindible para mantener el estilo simple.
try:
    import yt_dlp  # si no estuviera instalado, se maneja más abajo (yt_dlp=None)
except Exception:
    yt_dlp = None

# imageio-ffmpeg: opcional. Puede proveer un binario ffmpeg portátil (sin instalarlo en el sistema).
try:
    import imageio_ffmpeg  # sólo si está instalado
except Exception:
    imageio_ffmpeg = None

# Template en el mismo directorio
app = Flask(__name__, template_folder='.')

# Carpeta para guardar descargas
BASE_DIR = os.path.dirname(__file__)
DOWNLOAD_DIR = os.path.join(BASE_DIR, 'downloads')
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
MIN_SIZE = 100 * 1024  # tamaño mínimo para considerar que el archivo es válido (100KB)


def is_platform_url(url: str) -> bool:
    """Detecta URLs de plataformas comunes por dominio (heurística simple)."""
    domains = ['instagram.com', 'youtu.be', 'youtube.com', 'tiktok.com']
    return any(d in url for d in domains)

def sanitize_name(name: str) -> str:
    """
    Sanea el nombre para sistema de archivos y URL:
    - Permite letras, números, punto, guion y guion bajo.
    - Reemplaza cualquier otro carácter (espacios, acentos, emojis, comillas, etc.) por "_".
    - Evita nombres vacíos o que terminen en separadores.
    """
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._-")
    if not safe:
        return "archivo.mp4"
    return safe

def download_with_ytdlp(url: str, dest_dir: str) -> str:
    """
    Descarga usando yt-dlp.
    - Si hay ffmpeg (del sistema o portable), pide bestvideo+bestaudio y remux a mp4.
    - Si no hay ffmpeg, pide un stream progresivo único (best[ext=mp4]/best) para evitar fusión.
    Devuelve el nombre de archivo (basename) que quedó en dest_dir.
    """
    if yt_dlp is None:
        raise RuntimeError('yt-dlp no está disponible en el entorno.')

    # Detectar ffmpeg del sistema o portátil
    ffmpeg_path = shutil.which('ffmpeg')
    if not ffmpeg_path and imageio_ffmpeg is not None:
        try:
            ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            ffmpeg_path = None

    # Si hay ffmpeg, usamos mejor calidad (video+audio) y salida mp4.
    # Si no, usamos 'best' para intentar un formato progresivo único.
    opts = {
        'outtmpl': os.path.join(dest_dir, '%(title)s.%(ext)s'),
        'noplaylist': True,
        'quiet': True,
    }
    if ffmpeg_path:
        # Razonamiento: muchas plataformas entregan audio y video por separado.
        # ffmpeg permite fusionarlos y dejar un mp4 reproducible de forma general.
        opts['ffmpeg_location'] = ffmpeg_path
        opts['merge_output_format'] = 'mp4'
        opts['format'] = 'bestvideo+bestaudio/best'
        # Preferir ffmpeg y remux a mp4 con un postprocesador mínimo
        opts['prefer_ffmpeg'] = True
        opts['postprocessors'] = [{
            'key': 'FFmpegVideoRemuxer',
            'preferedformat': 'mp4'
        }]
    else:
        # fallback sin ffmpeg: intentar un stream único progresivo si existe
        opts['format'] = 'best[ext=mp4]/best'

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)
        # Si hay ffmpeg, normalmente remuxea/mergea a mp4
        if ffmpeg_path:
            base, _ = os.path.splitext(filename)
            final_path = base + '.mp4'
            filename = final_path if os.path.exists(final_path) else filename
        orig = os.path.basename(filename)
        safe = sanitize_name(orig)
        # Si difiere, renombrar
        if safe != orig:
            src = os.path.join(dest_dir, orig)
            dst = os.path.join(dest_dir, safe)
            if os.path.exists(src):
                try:
                    os.replace(src, dst)
                    return safe
                except OSError:
                    # Si no se puede renombrar, devolver original
                    return orig
        return orig


@app.route('/', methods=['GET', 'POST'])
def index():
    """
    Vista principal:
    - GET: muestra el formulario.
    - POST:
      * Si el URL es de plataforma (heurística de dominio), usa yt-dlp.
      * Si no, intenta descarga directa con requests (permitimos sólo video/* o extensiones típicas).
    """
    url = ''
    msg = ''
    saved = None

    if request.method == 'POST':
        url = request.form.get('url', '').strip()
        if not url:
            msg = 'Ingresa un URL.'
            return render_template('index.html', url=url, msg=msg, saved=saved)

        if is_platform_url(url):
            # Caso plataformas: usar yt-dlp
            # Razón: las páginas de plataformas no exponen un archivo directo, yt-dlp se encarga.
            try:
                saved = download_with_ytdlp(url, DOWNLOAD_DIR)
                dest = os.path.join(DOWNLOAD_DIR, saved)
                if not (os.path.isfile(dest) and os.path.getsize(dest) >= MIN_SIZE):
                    msg = 'Descarga completada pero el archivo parece inválido o demasiado pequeño.'
                    saved = None
                else:
                    msg = f'Descargado (yt-dlp): {saved}'
            except Exception as e:
                msg = f'No se pudo descargar con yt-dlp: {e}'
            return render_template('index.html', url=url, msg=msg, saved=saved)

        # Caso directo: GET simple del archivo
        # Razón: cuando el URL apunta a un archivo real (video/* o termina en .mp4/.webm/...)
        # es más rápido y confiable usar requests.
        try:
            resp = requests.get(url, stream=True, timeout=20)
        except requests.exceptions.RequestException as e:
            msg = f'Error de red: {e}'
            return render_template('index.html', url=url, msg=msg, saved=saved)

        ct = (resp.headers.get('Content-Type') or '').lower()
        # Aceptar si es video/* o si el URL termina con extensión de video
        # Por qué: evita guardar HTML como .mp4 corrupto.
        name = os.path.basename(urllib.parse.urlparse(url).path)
        ext = os.path.splitext(name)[1].lower()
        is_video_ext = ext in {'.mp4', '.webm', '.ogg', '.mov'}

        if not (ct.startswith('video/') or is_video_ext):
            msg = f'El URL no parece ser un archivo de video directo (Content-Type: {ct}).'
            return render_template('index.html', url=url, msg=msg, saved=saved)

        if not name:
            name = 'video.mp4'
        if '.' not in name:
            # Si no hay extensión, usar .mp4
            name = name + '.mp4'
        name = sanitize_name(name)
        dest = os.path.join(DOWNLOAD_DIR, name)
        try:
            with open(dest, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            # Verificación de tamaño mínimo: previene ofrecer un archivo inválido/vacío.
            if os.path.getsize(dest) < MIN_SIZE:
                msg = 'Descarga completada pero el archivo parece inválido o demasiado pequeño.'
            else:
                saved = name
                msg = f'Descargado como {name}'
        except OSError as e:
            msg = f'Error al guardar: {e}'

    return render_template('index.html', url=url, msg=msg, saved=saved)


@app.route('/download/<filename>')
def download(filename):
    # Sirve el archivo desde la carpeta downloads como adjunto (descarga forzada).
    return send_from_directory(DOWNLOAD_DIR, filename, as_attachment=True)


if __name__ == '__main__':
    # debug=True ayuda durante desarrollo (auto-reload y trazas de error visibles).
    app.run(debug=True)