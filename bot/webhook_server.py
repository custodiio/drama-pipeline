"""
Webhook Server — Recebe notificações dos notebooks Kaggle
+ API de sessão para o VideoRender (salvar config no Drive).
"""

import os
import json
import logging
import mimetypes
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
import threading
from dotenv import load_dotenv

load_dotenv()

from bot.database import update_step, cell_start, cell_end
from bot.pipeline_controller import PipelineController

logger = logging.getLogger(__name__)

controller = PipelineController()

# Diretório do VideoRender Frontend (build estático)
_FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "videorender-frontend", "dist")

# Referência para sessões ativas (importado do telegram_bot em runtime)
_session_validator = None
_seo_notifier = None  # função(project_id) chamada quando cel5 finaliza

def set_session_validator(validator_func):
    """Recebe a função validar_sessao do telegram_bot."""
    global _session_validator
    _session_validator = validator_func

def set_seo_notifier(notifier_func):
    """Recebe a função de notificação SEO do telegram_bot."""
    global _seo_notifier
    _seo_notifier = notifier_func


class PipelineWebhookHandler(BaseHTTPRequestHandler):
    """Handler HTTP para webhooks e API de sessão."""

    def _set_headers(self, code=200, content_type="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, Range")
        self.end_headers()

    def do_OPTIONS(self):
        """CORS preflight."""
        self._set_headers(204)

    def do_HEAD(self):
        """Responde HEAD reutilizando do_GET (BaseHTTPRequestHandler não gera automaticamente)."""
        self.do_GET()

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length)) if length else {}

    def do_GET(self):
        """Endpoints GET."""
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path == "/api/video":
            name = params.get("name", ["video.mp4"])[0]
            uploads_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")
            video_file = os.path.join(uploads_dir, name)
            
            if not os.path.exists(video_file):
                self._set_headers(404)
                self.wfile.write(json.dumps({"error": "Video not found"}).encode())
                return

            file_size = os.path.getsize(video_file)
            range_header = self.headers.get("Range")
            
            if range_header:
                byte_range = range_header.replace("bytes=", "").split("-")
                start = int(byte_range[0])
                end = int(byte_range[1]) if byte_range[1] else file_size - 1
                content_length = end - start + 1
                
                self.send_response(206)  # Partial Content
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Content-Length", str(content_length))
                self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, Range")
                self.end_headers()
                
                try:
                    with open(video_file, "rb") as f:
                        f.seek(start)
                        remaining = content_length
                        while remaining > 0:
                            chunk_size = min(65536, remaining)
                            chunk = f.read(chunk_size)
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            remaining -= len(chunk)
                except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                    pass  # Browser cancelou a conexão (normal)
            else:
                self.send_response(200)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Content-Length", str(file_size))
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, Range")
                self.end_headers()
                
                try:
                    with open(video_file, "rb") as f:
                        while True:
                            chunk = f.read(65536)
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                    pass  # Browser cancelou a conexão (normal)

        elif path == "/upload":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            html = """
            <!DOCTYPE html>
            <html lang="pt-BR">
            <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
            <meta name="apple-mobile-web-app-capable" content="yes">
            <title>Upload DramaRecap</title>
            <style>
                * { box-sizing: border-box; margin: 0; padding: 0; }
                body {
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    background: linear-gradient(135deg, #0d0d1a 0%, #1a0a2e 50%, #0d1a2e 100%);
                    color: #e0e0e0;
                    min-height: 100vh;
                    padding: 16px;
                    -webkit-tap-highlight-color: transparent;
                }
                .container {
                    max-width: 540px;
                    margin: 0 auto;
                    background: rgba(30, 30, 46, 0.85);
                    backdrop-filter: blur(12px);
                    -webkit-backdrop-filter: blur(12px);
                    padding: 28px 20px;
                    border-radius: 16px;
                    border: 1px solid rgba(187, 134, 252, 0.15);
                    box-shadow: 0 8px 32px rgba(0,0,0,0.4);
                }
                h2 {
                    color: #bb86fc;
                    font-size: 1.4rem;
                    margin-bottom: 8px;
                    text-align: center;
                }
                .subtitle {
                    text-align: center;
                    font-size: 0.85rem;
                    color: #888;
                    margin-bottom: 24px;
                }
                .upload-zone {
                    border: 2px dashed #bb86fc;
                    padding: 32px 16px;
                    text-align: center;
                    border-radius: 12px;
                    margin-bottom: 12px;
                    cursor: pointer;
                    transition: all 0.25s ease;
                    position: relative;
                    overflow: hidden;
                    -webkit-user-select: none;
                    user-select: none;
                }
                .upload-zone:active {
                    transform: scale(0.97);
                    background: rgba(187, 134, 252, 0.08);
                }
                .upload-zone.audio-zone {
                    border-color: #03dac6;
                }
                .upload-zone.audio-zone:active {
                    background: rgba(3, 218, 198, 0.08);
                }
                .upload-zone .icon {
                    font-size: 2.4rem;
                    margin-bottom: 8px;
                    display: block;
                }
                .upload-zone .label {
                    font-size: 1rem;
                    font-weight: 600;
                }
                .upload-zone .hint {
                    font-size: 0.75rem;
                    color: #888;
                    margin-top: 4px;
                }
                .upload-zone input[type="file"] {
                    position: absolute;
                    top: 0; left: 0;
                    width: 100%; height: 100%;
                    opacity: 0;
                    cursor: pointer;
                    font-size: 200px; /* iOS hack to make entire zone clickable */
                }
                .upload-zone.success {
                    border-color: #4CAF50 !important;
                    background: rgba(76, 175, 80, 0.08);
                }
                .upload-zone.uploading {
                    border-color: #FFB74D !important;
                    opacity: 0.85;
                    pointer-events: none;
                }
                .progress {
                    height: 6px;
                    background: rgba(255,255,255,0.08);
                    border-radius: 6px;
                    overflow: hidden;
                    margin-bottom: 20px;
                    opacity: 0;
                    transition: opacity 0.3s;
                }
                .progress.active { opacity: 1; }
                .progress-bar {
                    height: 100%;
                    background: linear-gradient(90deg, #bb86fc, #03dac6);
                    width: 0%;
                    transition: width 0.2s;
                    border-radius: 6px;
                }
                .progress.audio-prog .progress-bar {
                    background: linear-gradient(90deg, #03dac6, #00bfa5);
                }
                #status {
                    margin-top: 16px;
                    padding: 12px;
                    border-radius: 8px;
                    font-size: 0.85rem;
                    line-height: 1.6;
                    white-space: pre-wrap;
                    display: none;
                    background: rgba(3, 218, 198, 0.06);
                    border: 1px solid rgba(3, 218, 198, 0.15);
                    color: #03dac6;
                }
                #status.visible { display: block; }
                .footer-tip {
                    margin-top: 20px;
                    font-size: 0.78rem;
                    color: #777;
                    text-align: center;
                    line-height: 1.5;
                }
                .footer-tip b { color: #bb86fc; }

                @media (max-width: 480px) {
                    body { padding: 12px 8px; }
                    .container { padding: 20px 14px; border-radius: 12px; }
                    h2 { font-size: 1.2rem; }
                    .upload-zone { padding: 28px 12px; }
                    .upload-zone .icon { font-size: 2rem; }
                }
            </style>
            </head>
            <body>
            <div class="container">
                <h2>📤 Upload DramaRecap</h2>
                <p class="subtitle">Toque para selecionar ou arraste o arquivo</p>

                <div class="upload-zone" id="zone-video">
                    <span class="icon">🎬</span>
                    <span class="label">Selecionar VÍDEO</span>
                    <span class="hint">.mp4, .mkv, .avi, .mov, .webm</span>
                    <input type="file" id="input-video" accept="video/*, .mp4, .mkv, .avi, .mov, .webm">
                </div>
                <div class="progress" id="prog-video"><div class="progress-bar" id="bar-video"></div></div>

                <div class="upload-zone audio-zone" id="zone-audio">
                    <span class="icon">🎵</span>
                    <span class="label">Selecionar ÁUDIO</span>
                    <span class="hint">.mp3, .wav, .m4a, .aac, .ogg</span>
                    <input type="file" id="input-audio" accept="audio/*, .mp3, .wav, .m4a, .aac, .ogg, audio/mpeg, audio/mp3, audio/wav, audio/x-wav, audio/x-m4a, audio/m4a, audio/ogg, audio/aac">
                </div>
                <div class="progress audio-prog" id="prog-audio"><div class="progress-bar" id="bar-audio"></div></div>

                <div id="status"></div>
                <p class="footer-tip">Após enviar os dois arquivos, vá no Telegram e use<br><b>/usar_local Nome do Drama</b></p>
            </div>
            <script>
            (function() {
                function setupUpload(zoneId, inputId, barId, progId, fileType) {
                    var zone = document.getElementById(zoneId);
                    var input = document.getElementById(inputId);
                    var bar = document.getElementById(barId);
                    var prog = document.getElementById(progId);
                    var statusEl = document.getElementById('status');
                    var labelEl = zone.querySelector('.label');
                    var hintEl = zone.querySelector('.hint');

                    function doUpload(file) {
                        if (!file) return;
                        zone.classList.add('uploading');
                        labelEl.textContent = 'Enviando: ' + file.name;
                        hintEl.textContent = 'Aguarde...';
                        prog.classList.add('active');
                        bar.style.width = '0%';

                        var xhr = new XMLHttpRequest();
                        xhr.open('POST', '/api/upload-file?type=' + fileType + '&name=' + encodeURIComponent(file.name));

                        xhr.upload.onprogress = function(ev) {
                            if (ev.lengthComputable) {
                                var pct = Math.round(ev.loaded / ev.total * 100);
                                bar.style.width = pct + '%';
                                hintEl.textContent = pct + '%';
                            }
                        };

                        xhr.onload = function() {
                            zone.classList.remove('uploading');
                            if (xhr.status === 200) {
                                zone.classList.add('success');
                                labelEl.textContent = '✅ ' + file.name;
                                hintEl.textContent = 'Enviado com sucesso!';
                                statusEl.classList.add('visible');
                                statusEl.textContent += '✅ ' + file.name + ' salvo!\\n';
                            } else {
                                labelEl.textContent = '❌ Erro no upload';
                                hintEl.textContent = 'Toque para tentar novamente';
                            }
                        };

                        xhr.onerror = function() {
                            zone.classList.remove('uploading');
                            labelEl.textContent = '❌ Falha de conexão';
                            hintEl.textContent = 'Toque para tentar novamente';
                        };

                        xhr.send(file);
                    }

                    // File input change (funciona em iOS, Android, Desktop)
                    input.addEventListener('change', function(e) {
                        var file = e.target.files[0];
                        doUpload(file);
                    });

                    // Drag & drop (funciona em Desktop)
                    zone.addEventListener('dragover', function(e) {
                        e.preventDefault();
                        e.stopPropagation();
                        zone.style.background = 'rgba(187,134,252,0.08)';
                    });
                    zone.addEventListener('dragleave', function(e) {
                        e.preventDefault();
                        e.stopPropagation();
                        zone.style.background = '';
                    });
                    zone.addEventListener('drop', function(e) {
                        e.preventDefault();
                        e.stopPropagation();
                        zone.style.background = '';
                        var file = e.dataTransfer.files[0];
                        doUpload(file);
                    });
                }

                setupUpload('zone-video', 'input-video', 'bar-video', 'prog-video', 'video');
                setupUpload('zone-audio', 'input-audio', 'bar-audio', 'prog-audio', 'audio');
            })();
            </script>
            </body>
            </html>
            """
            self.wfile.write(html.encode("utf-8"))

        elif path == "/api/session/validate":
            token = params.get("token", [""])[0]
            if not token or not _session_validator:
                self._set_headers(200)
                self.wfile.write(json.dumps({"valid": False}).encode())
                return

            session = _session_validator(token)
            if session:
                self._set_headers(200)
                self.wfile.write(json.dumps({
                    "valid": True,
                    "project_id": session["project_id"]
                }).encode())
            else:
                self._set_headers(200)
                self.wfile.write(json.dumps({"valid": False}).encode())

        elif path == "/api/session/video":
            token = params.get("token", [""])[0]
            if not token or not _session_validator:
                self._set_headers(401)
                self.wfile.write(json.dumps({"error": "Unauthorized"}).encode())
                return

            session = _session_validator(token)
            if not session:
                self._set_headers(401)
                self.wfile.write(json.dumps({"error": "Invalid session"}).encode())
                return

            # Buscar vídeo do projeto na pasta uploads
            uploads_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")
            video_file = None
            if os.path.exists(uploads_dir):
                for f in os.listdir(uploads_dir):
                    if any(f.lower().endswith(ext) for ext in [".mp4", ".mkv", ".avi", ".mov", ".webm"]):
                        video_file = os.path.join(uploads_dir, f)
                        break

            if not video_file or not os.path.exists(video_file):
                self._set_headers(404)
                self.wfile.write(json.dumps({"error": "Video not found"}).encode())
                return

            file_size = os.path.getsize(video_file)
            range_header = self.headers.get("Range")

            if range_header:
                byte_range = range_header.replace("bytes=", "").split("-")
                start = int(byte_range[0])
                end = int(byte_range[1]) if byte_range[1] else file_size - 1
                content_length = end - start + 1

                self.send_response(206)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Content-Length", str(content_length))
                self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, Range")
                self.end_headers()

                try:
                    with open(video_file, "rb") as f:
                        f.seek(start)
                        remaining = content_length
                        while remaining > 0:
                            chunk_size = min(65536, remaining)
                            chunk = f.read(chunk_size)
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            remaining -= len(chunk)
                except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                    pass
            else:
                self.send_response(200)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Content-Length", str(file_size))
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, Range")
                self.end_headers()

                try:
                    with open(video_file, "rb") as f:
                        while True:
                            chunk = f.read(65536)
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                    pass

        elif path == "/api/overlays":
            from bot.database import get_all_overlays
            try:
                overlays = get_all_overlays()
                self._set_headers(200)
                self.wfile.write(json.dumps(overlays).encode())
            except Exception as e:
                self._set_headers(500)
                self.wfile.write(json.dumps({"error": str(e)}).encode())

        elif path == "/api/presets":
            from bot.database import get_all_presets
            try:
                presets = get_all_presets()
                self._set_headers(200)
                self.wfile.write(json.dumps(presets).encode())
            except Exception as e:
                self._set_headers(500)
                self.wfile.write(json.dumps({"error": str(e)}).encode())

        else:
            # Tentar servir arquivo estático do VideoRender Frontend
            if not self._serve_static(path):
                self._set_headers(404)
                self.wfile.write(json.dumps({"error": "Not found"}).encode())

    def _serve_static(self, url_path):
        """Serve arquivos estáticos do VideoRender Frontend (dist/)."""
        if not os.path.isdir(_FRONTEND_DIR):
            return False

        # Normalizar path: / -> /index.html
        file_path = url_path.lstrip("/")
        if not file_path:
            file_path = "index.html"

        full_path = os.path.join(_FRONTEND_DIR, file_path.replace("/", os.sep))

        # Se não existe, servir index.html (SPA client-side routing)
        if not os.path.isfile(full_path):
            full_path = os.path.join(_FRONTEND_DIR, "index.html")

        if not os.path.isfile(full_path):
            return False

        # Detectar MIME type
        mime, _ = mimetypes.guess_type(full_path)
        if not mime:
            mime = "application/octet-stream"

        try:
            file_size = os.path.getsize(full_path)
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(file_size))
            self.send_header("Access-Control-Allow-Origin", "*")
            # Cache para assets estáticos (js, css, imagens)
            if any(full_path.endswith(ext) for ext in [".js", ".css", ".woff2", ".png", ".svg"]):
                self.send_header("Cache-Control", "public, max-age=31536000, immutable")
            self.end_headers()

            with open(full_path, "rb") as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
            return True
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            return True
        except Exception:
            return False

    def do_DELETE(self):
        """Endpoints DELETE."""
        parsed = urlparse(self.path)
        path = parsed.path
        
        if path == "/api/overlays":
            params = parse_qs(parsed.query)
            overlay_id = params.get("id", [""])[0]
            if not overlay_id:
                self._set_headers(400)
                self.wfile.write(json.dumps({"error": "Missing id"}).encode())
                return
                
            from bot.database import delete_overlay
            try:
                success = delete_overlay(overlay_id)
                self._set_headers(200)
                self.wfile.write(json.dumps({"ok": success}).encode())
            except Exception as e:
                self._set_headers(500)
                self.wfile.write(json.dumps({"error": str(e)}).encode())

        elif path == "/api/presets":
            params = parse_qs(parsed.query)
            preset_id = params.get("id", [""])[0]
            if not preset_id:
                self._set_headers(400)
                self.wfile.write(json.dumps({"error": "Missing id"}).encode())
                return

            from bot.database import delete_preset
            try:
                success = delete_preset(preset_id)
                self._set_headers(200)
                self.wfile.write(json.dumps({"ok": success}).encode())
            except Exception as e:
                self._set_headers(500)
                self.wfile.write(json.dumps({"error": str(e)}).encode())

        else:
            self._set_headers(404)
            self.wfile.write(json.dumps({"error": "Not found"}).encode())

    def do_POST(self):
        """Endpoints POST."""
        path = urlparse(self.path).path

        try:
            parsed = urlparse(self.path)
            path = parsed.path

            if path == "/api/upload-file":
                params = parse_qs(parsed.query)
                file_type = params.get("type", [""])[0]
                file_name = params.get("name", ["arquivo"])[0]
                
                uploads_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")
                os.makedirs(uploads_dir, exist_ok=True)
                
                # Deleta arquivos do mesmo tipo antes de salvar o novo
                video_exts = [".mp4", ".mkv", ".avi", ".mov", ".webm"]
                audio_exts = [".mp3", ".wav", ".m4a", ".ogg", ".aac"]
                
                for existing in os.listdir(uploads_dir):
                    existing_path = os.path.join(uploads_dir, existing)
                    if os.path.isfile(existing_path):
                        if file_type == "video" and any(existing.lower().endswith(e) for e in video_exts):
                            try:
                                os.remove(existing_path)
                                logger.info(f"Vídeo antigo deletado localmente: {existing}")
                            except: pass
                        elif file_type == "audio" and any(existing.lower().endswith(e) for e in audio_exts):
                            try:
                                os.remove(existing_path)
                                logger.info(f"Áudio antigo deletado localmente: {existing}")
                            except: pass
                
                length = int(self.headers.get("Content-Length", 0))
                file_path = os.path.join(uploads_dir, file_name)
                
                with open(file_path, "wb") as f:
                    bytes_read = 0
                    while bytes_read < length:
                        chunk = self.rfile.read(min(8192*8, length - bytes_read))
                        if not chunk: break
                        f.write(chunk)
                        bytes_read += len(chunk)
                        
                self._set_headers(200)
                self.wfile.write(json.dumps({"ok": True, "path": file_path}).encode())
                return

            # Note: _read_body reads everything into JSON, so we do it AFTER /upload-file
            data = self._read_body()

            # ── Webhook: Status macro do notebook ──
            if path == "/webhook/status":
                pid = data.get("project_id")
                step = data.get("step")
                status = data.get("status")
                msg = data.get("message", "")

                if pid and step and status:
                    update_step(pid, step, status, msg)
                    controller.verificar_e_avancar(pid)
                    self._set_headers(200)
                    self.wfile.write(json.dumps({"ok": True}).encode())
                else:
                    self._set_headers(400)
                    self.wfile.write(json.dumps({"error": "Missing fields"}).encode())

            # ── API: Salvar Overlay no DB ──
            elif path == "/api/overlays":
                name = data.get("name")
                image_data = data.get("image_data")
                if not name or not image_data:
                    self._set_headers(400)
                    self.wfile.write(json.dumps({"error": "Missing name or image_data"}).encode())
                    return
                
                from bot.database import save_overlay
                try:
                    row = save_overlay(name, image_data)
                    self._set_headers(200)
                    self.wfile.write(json.dumps({"ok": True, "overlay": row}).encode())
                except Exception as e:
                    self._set_headers(500)
                    self.wfile.write(json.dumps({"error": str(e)}).encode())

            # ── API: Salvar Preset no DB ──
            elif path == "/api/presets":
                name = data.get("name")
                preset_data = data.get("preset_data")
                if not name or preset_data is None:
                    self._set_headers(400)
                    self.wfile.write(json.dumps({"error": "Missing name or preset_data"}).encode())
                    return

                from bot.database import save_preset
                try:
                    row = save_preset(name, preset_data)
                    self._set_headers(200)
                    self.wfile.write(json.dumps({"ok": True, "preset": row}).encode())
                except Exception as e:
                    self._set_headers(500)
                    self.wfile.write(json.dumps({"error": str(e)}).encode())

            # ── Webhook: Cell tracking ──
            elif path == "/webhook/cell-start":
                cell_start(data.get("project_id"), data.get("notebook"),
                              data.get("cell_index"), data.get("cell_name", ""))
                self._set_headers(200)
                self.wfile.write(json.dumps({"ok": True}).encode())

            elif path == "/webhook/cell-end":
                nb = data.get("notebook", "")
                cell_idx = data.get("cell_index")
                cell_status = data.get("status", "done")
                pid = data.get("project_id")
                cell_end(pid, nb, cell_idx, cell_status, data.get("message", ""))

                # Trigger SEO automático quando cel4 (tradução simplificada) finaliza
                if cell_idx == 4 and cell_status == "done" and pid and _seo_notifier:
                    import threading
                    threading.Thread(
                        target=_seo_notifier,
                        args=(pid,),
                        daemon=True
                    ).start()
                    logger.info(f"[SEO] Trigger disparado para projeto {pid} (cel4 done)")

                self._set_headers(200)
                self.wfile.write(json.dumps({"ok": True}).encode())

            # ── API: Salvar config do VideoRender no Drive ──
            elif path == "/api/session/save-config":
                token = data.get("token")
                config = data.get("config")  # JSON do videorender-project
                ass_content = data.get("ass")  # Conteúdo do .ass

                if not _session_validator:
                    self._set_headers(500)
                    self.wfile.write(json.dumps({"error": "Session system not initialized"}).encode())
                    return

                session = _session_validator(token)
                if not session:
                    self._set_headers(401)
                    self.wfile.write(json.dumps({"error": "Sessão inválida"}).encode())
                    return

                # Salvar config no Drive
                try:
                    from bot.drive_manager import DriveManager
                    import tempfile
                    dm = DriveManager()

                    # Salvar videorender-project.json
                    if config:
                        config_path = os.path.join(tempfile.gettempdir(), "videorender-project.json")
                        with open(config_path, "w", encoding="utf-8") as f:
                            json.dump(config, f, ensure_ascii=False)
                        dm.salvar(config_path, "DRAMA/PIPELINE/OMNI/videorender-project.json")
                        logger.info("Config salva no Drive")

                    # Salvar legendas.ass
                    if ass_content:
                        ass_path = os.path.join(tempfile.gettempdir(), "legendas.ass")
                        with open(ass_path, "w", encoding="utf-8") as f:
                            f.write(ass_content)
                        dm.salvar(ass_path, "DRAMA/PIPELINE/OMNI/legendas.ass")
                        logger.info("ASS salvo no Drive")
                        
                    # Salvar máscara (se enviada pelo VideoRender)
                    mask_data = data.get("mask") or data.get("mask_data")
                    if mask_data:
                        import base64
                        # Remover cabeçalho data:image/png;base64, se houver
                        if "," in mask_data:
                            mask_data = mask_data.split(",")[1]
                        
                        mask_path = os.path.join(tempfile.gettempdir(), "mask.png")
                        with open(mask_path, "wb") as f:
                            f.write(base64.b64decode(mask_data))
                        dm.salvar(mask_path, "DRAMA/PIPELINE/ATIVO/mask.png")
                        logger.info("Máscara salva no Drive/ATIVO")

                    # Marcar config como pronta no banco
                    update_step(session["project_id"], "step_config_ready", "done", "Config salva pelo VideoRender")

                    # Verificar se o pipeline pode avançar (ex: disparar watermark/enhancer ou render)
                    try:
                        from bot.pipeline_controller import PipelineController
                        ctrl = PipelineController()
                        ctrl.verificar_e_avancar(session["project_id"])
                    except Exception as ev:
                        logger.error(f"Erro ao verificar avanço: {ev}")

                    self._set_headers(200)
                    self.wfile.write(json.dumps({"ok": True, "message": "Config salva no Drive!"}).encode())

                except Exception as e:
                    logger.error(f"Erro ao salvar config: {e}")
                    self._set_headers(500)
                    self.wfile.write(json.dumps({"error": str(e)}).encode())

            else:
                self._set_headers(404)
                self.wfile.write(json.dumps({"error": "Not found"}).encode())

        except Exception as e:
            logger.error(f"Webhook error: {e}")
            self._set_headers(500)
            self.wfile.write(json.dumps({"error": str(e)}).encode())

    def log_message(self, format, *args):
        logger.info(f"[Webhook] {args[0]}")


def start_webhook_server(port=None):
    """Inicia o servidor webhook em background."""
    port = port or int(os.getenv("WEBHOOK_PORT", "8080"))

    server = HTTPServer(("0.0.0.0", port), PipelineWebhookHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info(f"Webhook server rodando na porta {port}")
    return server


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    port = int(os.getenv("WEBHOOK_PORT", "8080"))
    print(f"Iniciando webhook server na porta {port}...")
    server = HTTPServer(("0.0.0.0", port), PipelineWebhookHandler)
    server.serve_forever()
