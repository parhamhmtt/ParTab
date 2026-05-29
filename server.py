"""
LocalShare — instant file transfer between iOS and Windows over Wi-Fi.
Run this script, then open the displayed URL on your phone.
"""

import http.server
import socketserver
import socket
import json
import urllib.parse
import mimetypes
import html
from pathlib import Path
from datetime import datetime
import webbrowser
import psutil
import threading
import time

PORT = 8889
url = ""
last_ping = [None]
UPLOAD_DIR = Path(__file__).parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)


def get_local_ipv4() -> str:
    try:
        for iface, addrs in psutil.net_if_addrs().items():
            name = iface.lower()
            if any(x in name for x in ("wi-fi", "wifi", "wlan", "wireless")):
                for a in addrs:
                    if a.family == socket.AF_INET:
                        return a.address
    except ImportError:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def find_free_port(start: int) -> int:
    for port in range(start, start + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("", port))
                return port
            except OSError:
                continue
    raise OSError(f"No free port found in range {start}–{start + 20}")


def kill_port(port: int) -> bool:
    try:
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                for conn in proc.net_connections(kind="inet"):
                    if conn.laddr.port == port:
                        proc.kill()
                        print(f"  ⚠  Killed PID {proc.pid} ({proc.name()}) that was using port {port}.")
                        return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except ImportError:
        pass
    return False


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def list_uploads():
    items = []
    for p in sorted(UPLOAD_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if p.is_file():
            stat = p.stat()
            items.append({
                "name": p.name,
                "size": human_size(stat.st_size),
                "mtime": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
            })
    return items


class Handler(http.server.BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"  [{ts}]  {fmt % args}")

    def do_GET(self):
        try:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"

            if path == "/":
                self._serve_index()
            elif path == "/api/files":
                self._api_list()
            elif path.startswith("/download/"):
                filename = urllib.parse.unquote(path[len("/download/"):])
                self._serve_file(filename)
            elif path.startswith("/delete/"):
                filename = urllib.parse.unquote(path[len("/delete/"):])
                self._delete_file(filename)
            elif path == "/ping":
                client_ip = self.client_address[0]
                if client_ip in ("127.0.0.1", "::1"):
                    last_ping[0] = time.time()
                self._respond(200, "text/plain", b"ok")
            else:
                self._not_found()
        except Exception as e:
            print(f"  ✖  GET error: {e}")
            try:
                self._respond(500, "text/plain", b"Internal server error")
            except:
                pass

    def do_POST(self):
        try:
            if self.path == "/upload":
                self._handle_upload()
            else:
                self._not_found()
        except Exception as e:
            print(f"  ✖  POST error: {e}")
            try:
                self._respond(500, "text/plain", b"Internal server error")
            except:
                pass

    def _serve_index(self):
        body = HTML_PAGE.replace("__SERVER_URL__", url).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _api_list(self):
        self._respond(200, "application/json", json.dumps(list_uploads()).encode())

    def _serve_file(self, filename):
        safe = Path(filename).name
        filepath = UPLOAD_DIR / safe
        if not filepath.exists():
            self._not_found()
            return
        mime, _ = mimetypes.guess_type(str(filepath))
        mime = mime or "application/octet-stream"
        data = filepath.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", f'attachment; filename="{html.escape(safe)}"')
        self.end_headers()
        self.wfile.write(data)

    def _delete_file(self, filename):
        try:
            safe = Path(filename).name
            filepath = UPLOAD_DIR / safe
            if filepath.exists():
                filepath.unlink()
                print(f"  🗑  Deleted: {safe}")
                self._respond(200, "application/json", b'{"ok":true}')
            else:
                print(f"  ✖  Delete: file not found: {safe}")
                self._respond(404, "application/json", b'{"ok":false}')
        except Exception as e:
            print(f"  ✖  Delete error: {e}")
            try:
                self._respond(200, "application/json", b'{"ok":true}')
            except:
                pass

    def _handle_upload(self):
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            self._respond(400, "text/plain", b"Bad request")
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        boundary = None
        for part in content_type.split(";"):
            part = part.strip()
            if part.startswith("boundary="):
                boundary = part[9:].strip('"')
                break
        if not boundary:
            self._respond(400, "text/plain", b"No boundary")
            return

        saved = []
        sep = ("--" + boundary).encode()
        for chunk in body.split(sep)[1:]:
            if chunk in (b"--\r\n", b"--", b""):
                continue
            if b"\r\n\r\n" not in chunk:
                continue
            raw_headers, file_body = chunk.split(b"\r\n\r\n", 1)
            file_body = file_body.rstrip(b"\r\n")
            headers_str = raw_headers.decode("utf-8", errors="replace")

            filename = None
            for hline in headers_str.splitlines():
                if "Content-Disposition" in hline and "filename=" in hline:
                    for seg in hline.split(";"):
                        seg = seg.strip()
                        if seg.startswith("filename="):
                            filename = seg[9:].strip('"').strip("'")
                            break
            if not filename or not file_body:
                continue

            safe_name = Path(filename).name
            dest = UPLOAD_DIR / safe_name
            stem, suffix = dest.stem, dest.suffix
            counter = 1
            while dest.exists():
                dest = UPLOAD_DIR / f"{stem}_{counter}{suffix}"
                counter += 1

            dest.write_bytes(file_body)
            saved.append(safe_name)
            print(f"  ✔  Saved: {dest}  ({human_size(len(file_body))})")

        self._respond(200, "application/json", json.dumps({"saved": saved}).encode())

    def _respond(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _not_found(self):
        self._respond(404, "text/plain", b"Not found")


HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>LocalShare</title>
  <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 44 44'><rect width='44' height='44' rx='10' fill='%235cffb1'/><path d='M22 8L10 14l12 6 12-6-12-6z' fill='none' stroke='%230d0f14' stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round'/><path d='M10 26l12 6 12-6' fill='none' stroke='%230d0f14' stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round'/><path d='M10 20l12 6 12-6' fill='none' stroke='%230d0f14' stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round'/></svg>">
  <script src="https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js"></script>
  <style>
    :root {
      --bg: #0d0f14;
      --surface: #161920;
      --border: #252830;
      --accent: #5cffb1;
      --accent2: #4f9cff;
      --danger: #ff5c7a;
      --text: #e8eaf0;
      --muted: #6b7080;
      --radius: 14px;
      --font-mono: ui-monospace, 'SF Mono', 'Menlo', 'Consolas', 'Liberation Mono', monospace;
      --font-display: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'SF Pro Display', system-ui, sans-serif;
    }

    *, *::before, *::after {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }

    body {
      background: var(--bg);
      color: var(--text);
      font-family: var(--font-mono);
      min-height: 100dvh;
      padding: 24px 16px 60px;
    }

    header {
      display: flex;
      align-items: center;
      gap: 14px;
      margin-bottom: 32px;
    }

    .logo {
      width: 44px;
      height: 44px;
      background: var(--accent);
      border-radius: 12px;
      display: grid;
      place-items: center;
      flex-shrink: 0;
    }

    .logo svg {
      color: #0d0f14;
    }

    h1 {
      font-family: var(--font-display);
      font-size: clamp(1.4rem, 5vw, 2rem);
      font-weight: 800;
      letter-spacing: -.03em;
      line-height: 1;
    }

    h1 span {
      color: var(--accent);
    }

    .subtitle {
      font-size: .72rem;
      color: var(--muted);
      margin-top: 3px;
      letter-spacing: .06em;
    }

    #dropzone {
      border: 2px dashed var(--border);
      border-radius: var(--radius);
      padding: 40px 24px;
      text-align: center;
      cursor: pointer;
      transition: border-color .2s, background .2s;
      position: relative;
      margin-bottom: 20px;
      background: var(--surface);
    }

    #dropzone.drag-over {
      border-color: var(--accent);
      background: rgba(92, 255, 177, .05);
    }

    #dropzone input[type=file] {
      position: absolute;
      inset: 0;
      opacity: 0;
      cursor: pointer;
      width: 100%;
      height: 100%;
    }

    .drop-icon {
      width: 52px;
      height: 52px;
      background: rgba(92, 255, 177, .1);
      border-radius: 50%;
      display: grid;
      place-items: center;
      margin: 0 auto 14px;
      color: var(--accent);
    }

    .drop-label {
      font-size: .85rem;
      color: var(--muted);
      line-height: 1.6;
    }

    .drop-label strong {
      color: var(--text);
    }

    #upload-btn {
      width: 100%;
      padding: 14px;
      background: var(--accent);
      color: #0d0f14;
      font-family: var(--font-display);
      font-weight: 700;
      font-size: 1rem;
      border: none;
      border-radius: var(--radius);
      cursor: pointer;
      letter-spacing: .04em;
      transition: opacity .15s, transform .1s;
      display: none;
      margin-bottom: 24px;
    }

    #upload-btn:active {
      transform: scale(.98);
      opacity: .85;
    }

    #progress-wrap {
      display: none;
      margin-bottom: 18px;
    }

    #progress-bar-bg {
      background: var(--border);
      border-radius: 99px;
      height: 6px;
      overflow: hidden;
    }

    #progress-bar {
      height: 100%;
      background: linear-gradient(90deg, var(--accent), var(--accent2));
      border-radius: 99px;
      width: 0%;
      transition: width .2s;
    }

    #progress-label {
      font-size: .72rem;
      color: var(--muted);
      margin-top: 6px;
    }

    #toast {
      position: fixed;
      bottom: 50px;
      left: 50%;
      transform: translateX(-50%) translateY(80px);
      background: var(--surface);
      border: 1px solid var(--border);
      color: var(--text);
      padding: 10px 20px;
      border-radius: 99px;
      font-size: .8rem;
      transition: transform .3s cubic-bezier(.34, 1.56, .64, 1);
      white-space: nowrap;
      z-index: 999;
    }

    #toast.show {
      transform: translateX(-50%) translateY(0);
    }

    #toast.success {
      border-color: var(--accent);
      color: var(--accent);
    }

    #toast.error {
      border-color: var(--danger);
      color: var(--danger);
    }

    .section-title {
      font-family: var(--font-display);
      font-size: .7rem;
      font-weight: 700;
      letter-spacing: .12em;
      color: var(--muted);
      text-transform: uppercase;
      margin-bottom: 12px;
    }

    #file-list {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }

    .file-item {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 14px 16px;
      display: flex;
      align-items: center;
      gap: 12px;
      transition: border-color .15s;
    }

    .file-item:hover {
      border-color: #35394a;
    }

    .file-icon {
      width: 36px;
      height: 36px;
      background: rgba(79, 156, 255, .12);
      border-radius: 9px;
      display: grid;
      place-items: center;
      color: var(--accent2);
      flex-shrink: 0;
    }

    .file-info {
      flex: 1;
      min-width: 0;
    }

    .file-name {
      font-size: .85rem;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      color: var(--text);
    }

    .file-meta {
      font-size: .7rem;
      color: var(--muted);
      margin-top: 2px;
    }

    .file-actions {
      display: flex;
      gap: 6px;
      flex-shrink: 0;
    }

    .btn-icon {
      width: 32px;
      height: 32px;
      border: 1px solid var(--border);
      background: transparent;
      border-radius: 8px;
      cursor: pointer;
      display: grid;
      place-items: center;
      color: var(--muted);
      transition: color .15s, border-color .15s, background .15s;
    }

    .btn-icon:hover {
      color: var(--text);
      border-color: #35394a;
    }

    .btn-icon.danger:hover {
      color: var(--danger);
      border-color: var(--danger);
      background: rgba(255, 92, 122, .07);
    }

    .empty {
      text-align: center;
      color: var(--muted);
      font-size: .8rem;
      padding: 32px 0;
    }

    #queue-list {
      margin-bottom: 16px;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }

    .queue-item {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 10px 14px;
      display: flex;
      align-items: center;
      gap: 10px;
      font-size: .8rem;
      color: var(--muted);
    }

    .queue-item span {
      flex: 1;
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      color: var(--text);
    }

    #qr-wrap {
      position: relative;
      flex-shrink: 0;
      cursor: pointer;
      margin-left: auto;
    }

    #qr-box {
      width: 72px;
      height: 72px;
      background: #fff;
      border-radius: 10px;
      padding: 5px;
      display: flex;
      align-items: center;
      justify-content: center;
      box-shadow: 0 2px 12px rgba(0,0,0,.4);
      transition: transform .15s;
    }

    #qr-box:hover { transform: scale(1.05); }
    #qr-box canvas, #qr-box img { width: 100% !important; height: 100% !important; }

    #qr-label {
      text-align: center;
      font-size: .58rem;
      color: var(--muted);
      margin-top: 4px;
      letter-spacing: .05em;
      text-transform: uppercase;
    }

    /* Full-size QR popup on click */
    #qr-overlay {
      position: fixed;
      inset: 0;
      background: rgba(0,0,0,.7);
      backdrop-filter: blur(6px);
      display: none;
      place-items: center;
      z-index: 1000;
      cursor: pointer;
    }

    #qr-overlay.open { display: grid; }

    #qr-popup {
      background: #fff;
      border-radius: 16px;
      padding: 20px;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 12px;
      animation: pop-in .2s cubic-bezier(.34,1.56,.64,1);
    }

    #qr-popup-label {
      font-family: var(--font-display);
      font-size: .8rem;
      color: #333;
      font-weight: 600;
      letter-spacing: .02em;
    }

    @keyframes pop-in {
      from { transform: scale(.8); opacity: 0; }
      to   { transform: scale(1);  opacity: 1; }
    }
  </style>
</head>
<body>

  <header>
    <div class="logo">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M12 2L2 7l10 5 10-5-10-5z"/>
        <path d="M2 17l10 5 10-5"/>
        <path d="M2 12l10 5 10-5"/>
      </svg>
    </div>
    <div>
      <h1>Local<span>Share</span></h1>
      <div class="subtitle">iOS → Windows · same Wi-Fi</div>
      <div class="subtitle" id="server-url" style="margin-top:4px; color:var(--accent); letter-spacing:.02em">
        __SERVER_URL__
      </div>
    </div>
    <div id="qr-wrap" onclick="document.getElementById('qr-overlay').classList.add('open')" title="Click to enlarge">
      <div id="qr-box"></div>
    </div>
  </header>

  <!-- Full-size QR popup -->
  <div id="qr-overlay" onclick="this.classList.remove('open')">
    <div id="qr-popup" onclick="event.stopPropagation()">
      <div id="qr-popup-canvas"></div>
      <div id="qr-popup-label">__SERVER_URL__</div>
    </div>
  </div>

  <div id="dropzone">
    <input type="file" id="file-input" multiple accept="*/*">
    <div class="drop-icon">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="16 16 12 12 8 16"/>
        <line x1="12" y1="12" x2="12" y2="21"/>
        <path d="M20.39 18.39A5 5 0 0018 9h-1.26A8 8 0 103 16.3"/>
      </svg>
    </div>
    <div class="drop-label">
      <strong>Tap to choose files</strong><br>
      or drag &amp; drop from your device
    </div>
  </div>

  <div id="queue-list"></div>

  <button id="upload-btn">⬆ Upload Files</button>

  <div id="progress-wrap">
    <div id="progress-bar-bg">
      <div id="progress-bar"></div>
    </div>
    <div id="progress-label">Uploading…</div>
  </div>

  <div class="section-title">Files in uploads/</div>
  <div id="file-list">
    <div class="empty">No files yet.</div>
  </div>

  <div id="toast"></div>

  <script>
    const fileInput     = document.getElementById('file-input');
    const dropzone      = document.getElementById('dropzone');
    const uploadBtn     = document.getElementById('upload-btn');
    const queueList     = document.getElementById('queue-list');
    const progressWrap  = document.getElementById('progress-wrap');
    const progressBar   = document.getElementById('progress-bar');
    const progressLabel = document.getElementById('progress-label');
    const fileListEl    = document.getElementById('file-list');

    let selectedFiles = [];

    fileInput.addEventListener('change', () => {
      selectedFiles = Array.from(fileInput.files);
      renderQueue();
    });

    dropzone.addEventListener('dragover', e => {
      e.preventDefault();
      dropzone.classList.add('drag-over');
    });

    dropzone.addEventListener('dragleave', () => {
      dropzone.classList.remove('drag-over');
    });

    dropzone.addEventListener('drop', e => {
      e.preventDefault();
      dropzone.classList.remove('drag-over');
      selectedFiles = Array.from(e.dataTransfer.files);
      renderQueue();
    });

    function renderQueue() {
      queueList.innerHTML = '';
      if (!selectedFiles.length) {
        uploadBtn.style.display = 'none';
        return;
      }
      uploadBtn.style.display = 'block';
      selectedFiles.forEach(f => {
        const d = document.createElement('div');
        d.className = 'queue-item';
        d.innerHTML = `
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M13 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V9z"/>
            <polyline points="13 2 13 9 20 9"/>
          </svg>
          <span>${f.name}</span>
          <span style="color:var(--muted); flex-shrink:0">${humanSize(f.size)}</span>
        `;
        queueList.appendChild(d);
      });
    }

    function humanSize(n) {
      const u = ['B', 'KB', 'MB', 'GB'];
      let i = 0;
      while (n >= 1024 && i < u.length - 1) {
        n /= 1024;
        i++;
      }
      return n.toFixed(1) + ' ' + u[i];
    }

    uploadBtn.addEventListener('click', async () => {
      if (!selectedFiles.length) return;

      const fd = new FormData();
      selectedFiles.forEach(f => fd.append('file', f, f.name));

      progressWrap.style.display = 'block';
      uploadBtn.disabled = true;
      progressBar.style.width = '0%';

      const xhr = new XMLHttpRequest();
      xhr.open('POST', '/upload');

      xhr.upload.onprogress = e => {
        if (e.lengthComputable) {
          const p = Math.round(e.loaded / e.total * 100);
          progressBar.style.width = p + '%';
          progressLabel.textContent = `Uploading… ${p}%`;
        }
      };

      xhr.onload = () => {
        progressWrap.style.display = 'none';
        uploadBtn.disabled = false;
        if (xhr.status === 200) {
          const r = JSON.parse(xhr.responseText);
          toast(`✔ ${r.saved.length} file(s) saved`, 'success');
          selectedFiles = [];
          fileInput.value = '';
          queueList.innerHTML = '';
          uploadBtn.style.display = 'none';
          pausePoll();
          loadFiles().then(resumePoll);
        } else {
          toast('Upload failed', 'error');
        }
      };

      xhr.onerror = () => {
        progressWrap.style.display = 'none';
        uploadBtn.disabled = false;
        toast('Network error', 'error');
      };

      xhr.send(fd);
    });

    async function loadFiles() {
      try {
        const r = await fetch('/api/files');
        const files = await r.json();

        if (!files.length) {
          fileListEl.innerHTML = '<div class="empty">No files yet. Upload something!</div>';
          return;
        }

        fileListEl.innerHTML = files.map((f, i) => `
          <div class="file-item">
            <div class="file-icon">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M13 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V9z"/>
                <polyline points="13 2 13 9 20 9"/>
              </svg>
            </div>
            <div class="file-info">
              <div class="file-name" title="${esc(f.name)}">${esc(f.name)}</div>
              <div class="file-meta">${f.size} · ${f.mtime}</div>
            </div>
            <div class="file-actions">
              <a href="/download/${encodeURIComponent(f.name)}" download>
                <button class="btn-icon" title="Download">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polyline points="8 17 12 21 16 17"/>
                    <line x1="12" y1="12" x2="12" y2="21"/>
                    <path d="M20.88 18.09A5 5 0 0018 9h-1.26A8 8 0 103 16.3"/>
                  </svg>
                </button>
              </a>
              <button class="btn-icon danger" title="Delete" data-idx="${i}">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <polyline points="3 6 5 6 21 6"/>
                  <path d="M19 6l-1 14H6L5 6"/>
                  <path d="M10 11v6"/>
                  <path d="M14 11v6"/>
                  <path d="M9 6V4h6v2"/>
                </svg>
              </button>
            </div>
          </div>
        `).join('');

        document.querySelectorAll('.btn-icon.danger').forEach(btn => {
          const idx = parseInt(btn.dataset.idx, 10);
          btn.addEventListener('click', () => deleteFile(files[idx].name));
        });

      } catch (e) {
        console.error('loadFiles error:', e);
      }
    }

    async function deleteFile(n) {
      pausePoll();
      try {
        await fetch('/delete/' + encodeURIComponent(n));
      } catch (e) {}
      toast('Deleted', 'success');
      await loadFiles();
      resumePoll();
    }

    function esc(s) {
      return s
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
    }

    let toastTimer;
    function toast(msg, type = '') {
      const el = document.getElementById('toast');
      el.textContent = msg;
      el.className = 'show ' + type;
      clearTimeout(toastTimer);
      toastTimer = setTimeout(() => el.className = '', 2800);
    }

    let pollInterval = setInterval(loadFiles, 5000);

    function pausePoll() {
      clearInterval(pollInterval);
    }

    function resumePoll() {
      clearInterval(pollInterval);
      pollInterval = setInterval(loadFiles, 5000);
    }


    if (location.hostname === 'localhost' || location.hostname === '127.0.0.1') {
      setInterval(() => {
        fetch('/ping').catch(() => {});
      }, 10000);

      document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') {
          fetch('/ping').catch(() => {});
        }
      });
    }

    loadFiles();

    const mobileUrl = document.getElementById('server-url').textContent.trim();

    new QRCode(document.getElementById('qr-box'), {
      text: mobileUrl,
      width: 62,
      height: 62,
      colorDark: '#000000',
      colorLight: '#ffffff',
      correctLevel: QRCode.CorrectLevel.M
    });

    new QRCode(document.getElementById('qr-popup-canvas'), {
      text: mobileUrl,
      width: 220,
      height: 220,
      colorDark: '#000000',
      colorLight: '#ffffff',
      correctLevel: QRCode.CorrectLevel.M
    });
  </script>

<footer style="
    position:fixed;
    bottom:0;
    left:0;
    width:100%;
    padding:14px 0;
    text-align:center;
    background:#0d0f14;
    border-top:1px solid #252830;
    color:#6b7080;
    font-family:ui-monospace,'SF Mono','Menlo','Consolas',monospace;
    font-size:0.8rem;
    z-index:999;
">
    © 2026
    <a href="https://github.com/Parhamhmtt" target="_blank" style="
        color:#e8eaf0;
        text-decoration:none;
        font-weight:600;
    ">
        Parhamhmtt
    </a>
    —
    <span style="color:#ffffff;">Local</span><span style="color:#5cffb1;">Share</span>
</footer>
</body>
</html>"""


def main():
    global url

    port = PORT

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as test:
        test.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            test.bind(("", port))
        except OSError:
            print(f"\n  ⚠  Port {port} is already in use.")
            print("     Attempting to free it... ", end="", flush=True)
            freed = kill_port(port)
            if freed:
                print("done.")
                time.sleep(0.5)
            else:
                print("could not kill process (try manually or run as admin).")
                port = find_free_port(port + 1)
                print(f"     Falling back to port {port}.\n")

    ip = get_local_ipv4()
    url = f"http://{ip}:{port}"
    webbrowser.open(f"http://localhost:{port}")
    print()
    print("  ╔══════════════════════════════════════╗")
    print("             LocalShare  🚀              ")
    print("  ╠══════════════════════════════════════╣")
    print(f"  ║ Local  →  http://localhost:{port}      ║")
    print(f"  ║ Mobile →  {url:<27}║")
    print("  ╠══════════════════════════════════════╣")
    print("  ║  Open the Mobile URL on your iPhone  ║")
    print("  ║  (same Wi-Fi required)               ║")
    print("  ╚══════════════════════════════════════╝")
    print()
    print(f"  Uploads saved to: {UPLOAD_DIR}")
    print("  Press Ctrl+C to stop.\n")

    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("", port), Handler) as httpd:

        def heartbeat_monitor():
            while last_ping[0] is None:
                time.sleep(1)
            print("  ✔  PC tab connected — watching for disconnect.")
            while True:
                time.sleep(2)
                if time.time() - last_ping[0] > 90:
                    print("  🛑  Tab closed — shutting down.")
                    httpd.shutdown()
                    return

        threading.Thread(target=heartbeat_monitor, daemon=True).start()

        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n  Server stopped.")


if __name__ == "__main__":
    main()