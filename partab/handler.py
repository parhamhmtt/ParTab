import http.server
import html
from http.cookies import SimpleCookie
import json
import mimetypes
import queue
import threading
from pathlib import Path
import time
import urllib.parse
import uuid

from . import state
from .events import broker
from .files import human_size, list_uploads
from .page import get_html_page, get_waiting_page
from .paths import UPLOAD_DIR, UPLOAD_TMP_DIR, resource_path
from .qr import generate_qr_png
from .security import access_manager, describe_user_agent


ACCESS_COOKIE = "partab_access"
UPLOAD_FINALIZE_LOCK = threading.Lock()


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, fmt, *args):
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"  [{ts}]  {fmt % args}")

    def do_GET(self):
        try:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"

            if path == "/api/access/status":
                self._api_access_status(parsed)
                return

            if path == "/events/access":
                self._serve_access_events(parsed)
                return

            if not self._security_allows_request():
                if path == "/":
                    self._serve_approval_waiting()
                else:
                    self._respond_json(403, {"error": "approval_required"})
                return

            if path == "/":
                self._serve_index()
            elif path == "/api/files":
                self._api_list()
            elif path == "/api/security/status":
                self._api_security_status()
            elif path == "/api/security/pending":
                self._api_security_pending()
            elif path == "/events":
                self._serve_events()
            elif path.startswith("/download/"):
                filename = urllib.parse.unquote(path[len("/download/"):])
                self._serve_file(filename)
            elif path.startswith("/delete/"):
                filename = urllib.parse.unquote(path[len("/delete/"):])
                self._delete_file(filename)
            elif path == "/assets/logo.png":
                self._serve_asset("logo.png")
            elif path == "/qr.png":
                self._serve_qr()
            elif path == "/ping":
                client_ip = self.client_address[0]
                if self._is_host_client():
                    state.last_ping[0] = time.time()
                self._respond(200, "text/plain", b"ok")
            else:
                self._not_found()
        except Exception as e:
            print(f"  ✖  GET error: {e}")
            try:
                self._respond(500, "text/plain", b"Internal server error")
            except Exception:
                pass

    def do_POST(self):
        try:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"

            if path == "/api/security/mode":
                self._api_security_mode()
                return

            if path == "/api/security/decision":
                self._api_security_decision()
                return

            if path == "/api/system/exit":
                self._api_system_exit()
                return

            if not self._security_allows_request():
                self._respond_json(403, {"error": "approval_required"})
                return

            if path == "/upload":
                self._handle_upload()
            else:
                self._not_found()
        except Exception as e:
            print(f"  ✖  POST error: {e}")
            try:
                self._respond(500, "text/plain", b"Internal server error")
            except Exception:
                pass

    def _is_host_client(self):
        client_ip = self.client_address[0]
        host_ips = {"127.0.0.1", "::1"}
        if state.ip:
            host_ips.add(state.ip)
        return client_ip in host_ips

    def _client_user_agent(self):
        return self.headers.get("User-Agent", "")

    def _get_access_cookie(self):
        raw = self.headers.get("Cookie", "")
        if not raw:
            return None
        try:
            cookie = SimpleCookie()
            cookie.load(raw)
            morsel = cookie.get(ACCESS_COOKIE)
            return morsel.value if morsel else None
        except Exception:
            return None

    def _security_allows_request(self):
        if self._is_host_client() or not access_manager.secure:
            return True
        return access_manager.is_approved(
            self._get_access_cookie(),
            self.client_address[0],
            self._client_user_agent(),
        )

    def _serve_approval_waiting(self):
        request, created = access_manager.request_access(
            self.client_address[0],
            self._client_user_agent(),
        )
        if created:
            broker.publish("host", "connection_request", request.as_public_dict())
        body = (
            get_waiting_page()
            .replace("__REQUEST_ID__", request.request_id)
            .encode("utf-8")
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _api_access_status(self, parsed):
        params = urllib.parse.parse_qs(parsed.query)
        request_id = params.get("id", [""])[0]
        if not request_id:
            self._respond_json(400, {"status": "invalid"})
            return

        status, token = access_manager.access_status(
            request_id,
            self.client_address[0],
            self._client_user_agent(),
        )

        headers = None
        if status == "approved" and token:
            headers = {
                "Set-Cookie": (
                    f"{ACCESS_COOKIE}={token}; Path=/; HttpOnly; "
                    "SameSite=Strict; Max-Age=86400"
                )
            }

        self._respond_json(200, {"status": status}, headers=headers)

    def _serve_events(self):
        audiences = {"clients"}
        is_host = self._is_host_client()
        if is_host:
            audiences.add("host")
            state.last_ping[0] = time.time()

        subscriber_id, event_queue = broker.subscribe(audiences)
        try:
            self._start_sse()
            self._write_sse("ready", {
                "secure": access_manager.secure,
                "host": is_host,
            })

            while True:
                try:
                    event = event_queue.get(timeout=15)
                    self._write_sse(event.name, event.data, event.event_id)
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()

                if is_host:
                    state.last_ping[0] = time.time()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            broker.unsubscribe(subscriber_id)

    def _serve_access_events(self, parsed):
        params = urllib.parse.parse_qs(parsed.query)
        request_id = params.get("id", [""])[0]
        if not request_id:
            self._respond_json(400, {"error": "missing_request_id"})
            return

        status, _ = access_manager.access_status(
            request_id,
            self.client_address[0],
            self._client_user_agent(),
        )
        if status == "invalid":
            self._respond_json(403, {"error": "invalid_request"})
            return

        if status == "expired":
            self._respond_json(404, {"error": "expired_request"})
            return

        subscriber_id, event_queue = broker.subscribe({
            "access",
            f"access:{request_id}",
        })
        try:
            self._start_sse()
            status, _ = access_manager.access_status(
                request_id,
                self.client_address[0],
                self._client_user_agent(),
            )
            self._write_sse("access_status", {"status": status})

            while True:
                try:
                    event = event_queue.get(timeout=15)
                    self._write_sse(event.name, event.data, event.event_id)
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            broker.unsubscribe(subscriber_id)

    def _start_sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-store")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        self.wfile.write(b": connected\n\n")
        self.wfile.flush()

    def _write_sse(self, name, data, event_id=None):
        payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
        parts = []
        if event_id is not None:
            parts.append(f"id: {event_id}\n")
        parts.append(f"event: {name}\n")
        for line in payload.splitlines() or [""]:
            parts.append(f"data: {line}\n")
        parts.append("\n")
        self.wfile.write("".join(parts).encode("utf-8"))
        self.wfile.flush()

    def _api_security_status(self):
        self._respond_json(200, {
            "secure": access_manager.secure,
            "host": self._is_host_client(),
            "pending_count": (
                len(access_manager.pending_requests())
                if self._is_host_client() and access_manager.secure
                else 0
            ),
        })

    def _api_security_pending(self):
        if not self._is_host_client():
            self._respond_json(403, {"error": "host_only"})
            return
        self._respond_json(200, {
            "pending": access_manager.pending_requests()
            if access_manager.secure else []
        })

    def _api_security_mode(self):
        if not self._is_host_client():
            self._respond_json(403, {"error": "host_only"})
            return

        payload = self._read_json_body()
        if payload is None or not isinstance(payload.get("secure"), bool):
            self._respond_json(400, {"error": "invalid_request"})
            return

        enabled = access_manager.set_secure(payload["secure"])
        mode = "SECURED" if enabled else "INSECURE"
        print(f"  🔐  Access mode: {mode}")
        self._respond_json(200, {"secure": enabled})
        event_data = {"secure": enabled}
        broker.publish("clients", "security_changed", event_data)
        broker.publish("access", "security_changed", event_data)

    def _api_security_decision(self):
        if not self._is_host_client():
            self._respond_json(403, {"error": "host_only"})
            return

        payload = self._read_json_body()
        if payload is None:
            self._respond_json(400, {"error": "invalid_request"})
            return

        request_id = str(payload.get("request_id", ""))
        decision = payload.get("decision")
        if decision not in ("approve", "reject"):
            self._respond_json(400, {"error": "invalid_decision"})
            return

        changed = access_manager.decide(request_id, decision == "approve")
        if not changed:
            self._respond_json(404, {"error": "request_not_found"})
            return

        icon = "✔" if decision == "approve" else "✖"
        verb = "approved" if decision == "approve" else "rejected"
        print(f"  {icon}  Connection request {verb}: {request_id[:8]}")
        self._respond_json(200, {"ok": True})
        broker.publish(f"access:{request_id}", "access_decision", {"status": "approved" if decision == "approve" else "denied"})
        broker.publish("host", "pending_changed", {})

    def _api_system_exit(self):
        payload = self._read_json_body()

        if not self._is_host_client():
            self._respond_json(403, {"error": "host_only"})
            return

        if self.headers.get("X-ParTab-Host-Action") != "shutdown":
            self._respond_json(403, {"error": "invalid_host_action"})
            return

        if payload is None or payload.get("confirm") != "shutdown":
            self._respond_json(400, {"error": "confirmation_required"})
            return

        print("  🛑  Exit requested from host PC — shutting down ParTab.")
        self._respond_json(200, {"ok": True})

        event_data = {"reason": "host_exit"}
        broker.publish("clients", "server_shutdown", event_data)
        broker.publish("access", "server_shutdown", event_data)

        server = self.server

        def stop_server():
            time.sleep(0.8)
            server.shutdown()

        threading.Thread(target=stop_server, daemon=True).start()

    def _read_json_body(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 65536:
                return None
            raw = self.rfile.read(length)
            data = json.loads(raw.decode("utf-8"))
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def _serve_qr(self):
        data = generate_qr_png(state.url)
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _serve_asset(self, filename):
        asset = resource_path("assets") / filename
        if not asset.exists():
            self._not_found()
            return

        mime, _ = mimetypes.guess_type(str(asset))
        mime = mime or "application/octet-stream"
        data = asset.read_bytes()

        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_index(self):
        body = (
            get_html_page()
            .replace("__SERVER_URL__", state.url)
            .replace("__PORT__", str(state.port))
            .encode()
        )
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

        size = filepath.stat().st_size
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(size))
        self.send_header(
            "Content-Disposition",
            f'attachment; filename="{html.escape(safe)}"'
        )
        self.end_headers()

        with open(filepath, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)

    def _delete_file(self, filename):
        try:
            safe = Path(filename).name
            filepath = UPLOAD_DIR / safe
            if filepath.exists():
                filepath.unlink()
                print(f"  🗑  Deleted: {safe}")
                self._respond(200, "application/json", b'{"ok":true}')
                broker.publish("clients", "files_changed", {"action": "delete", "name": safe})
            else:
                print(f"  ✖  Delete: file not found: {safe}")
                self._respond(404, "application/json", b'{"ok":false}')
        except Exception as e:
            print(f"  ✖  Delete error: {e}")
            try:
                self._respond(200, "application/json", b'{"ok":true}')
            except Exception:
                pass

    def _handle_upload(self):
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            self._respond(400, "text/plain", b"Bad request")
            return
        boundary = None
        for part in content_type.split(";"):
            part = part.strip()
            if part.startswith("boundary="):
                boundary = part[9:].strip('"')
                break
        if not boundary:
            self._respond(400, "text/plain", b"No boundary")
            return

        raw_transfer_id = self.headers.get("X-ParTab-Transfer-ID", "")
        transfer_id = "".join(
            ch for ch in raw_transfer_id
            if ch.isalnum() or ch in "-_"
        )[:80]
        if not transfer_id:
            transfer_id = uuid.uuid4().hex

        boundary_bytes = ("--" + boundary).encode()
        length = int(self.headers.get("Content-Length", 0))
        saved = []
        buf = b""
        current_file = None
        current_dest = None
        current_name = None
        CHUNK = 65536
        bytes_read = 0
        last_progress_at = 0.0
        last_progress_percent = -1.0
        device = describe_user_agent(self._client_user_agent())
        client_ip = self.client_address[0]
        finished = False

        def transfer_payload(percent=None, status=None):
            payload = {
                "id": transfer_id,
                "name": current_name or "Receiving files…",
                "device": device,
                "ip": client_ip,
                "loaded": bytes_read,
                "total": length,
            }
            if percent is not None:
                payload["percent"] = percent
            if status is not None:
                payload["status"] = status
            return payload

        def publish_progress(force=False):
            nonlocal last_progress_at, last_progress_percent
            if length <= 0:
                return
            now = time.monotonic()
            percent = min(100.0, round((bytes_read / length) * 100, 1))
            if not force:
                advanced = percent - last_progress_percent >= 1.0
                elapsed = now - last_progress_at >= 0.25
                if not advanced and not elapsed:
                    return
            last_progress_at = now
            last_progress_percent = percent
            broker.publish("clients", "upload_progress", transfer_payload(percent))

        def publish_aborted():
            percent = 0.0 if length <= 0 else min(100.0, round((bytes_read / length) * 100, 1))
            broker.publish(
                "clients",
                "upload_aborted",
                transfer_payload(percent, "aborted"),
            )

        def open_temp_dest():
            return UPLOAD_TMP_DIR / f"{transfer_id}-{uuid.uuid4().hex}.part"

        def finalize_dest(temp_path, filename):
            safe_name = Path(filename).name
            with UPLOAD_FINALIZE_LOCK:
                dest = UPLOAD_DIR / safe_name
                stem, suffix = dest.stem, dest.suffix
                counter = 1
                while dest.exists():
                    dest = UPLOAD_DIR / f"{stem}_{counter}{suffix}"
                    counter += 1
                temp_path.replace(dest)
            return dest

        broker.publish(
            "clients",
            "upload_started",
            transfer_payload(0.0, "uploading"),
        )

        try:
            while bytes_read < length:
                to_read = min(CHUNK, length - bytes_read)
                chunk = self.rfile.read(to_read)
                if not chunk:
                    break
                bytes_read += len(chunk)
                buf += chunk
                publish_progress()

                while True:
                    if current_dest is None:
                        idx = buf.find(boundary_bytes)
                        if idx == -1:
                            break
                        buf = buf[idx + len(boundary_bytes):]

                        if buf.startswith(b"--"):
                            buf = b""
                            break

                        if buf.startswith(b"\r\n"):
                            buf = buf[2:]
                        hdr_end = buf.find(b"\r\n\r\n")
                        if hdr_end == -1:
                            break

                        raw_headers = buf[:hdr_end].decode("utf-8", errors="replace")
                        buf = buf[hdr_end + 4:]
                        filename = None
                        for hline in raw_headers.splitlines():
                            if "Content-Disposition" in hline and "filename=" in hline:
                                for seg in hline.split(";"):
                                    seg = seg.strip()
                                    if seg.startswith("filename="):
                                        filename = seg[9:].strip('"').strip("'")
                                        break
                        if not filename:
                            current_dest = None
                            continue
                        current_name = Path(filename).name
                        current_dest = open_temp_dest()
                        current_file = open(current_dest, "wb")
                        publish_progress(force=True)
                    else:
                        idx = buf.find(boundary_bytes)
                        if idx != -1:
                            data = buf[:idx]
                            if data.endswith(b"\r\n"):
                                data = data[:-2]
                            current_file.write(data)
                            current_file.close()
                            current_file = None
                            final_dest = finalize_dest(current_dest, current_name)
                            size = final_dest.stat().st_size
                            print(f"  ✔  Saved: {final_dest}  ({human_size(size)})")
                            saved.append(final_dest.name)
                            broker.publish(
                                "clients",
                                "files_changed",
                                {"action": "upload", "files": [final_dest.name]},
                            )
                            current_dest = None
                            buf = buf[idx:]
                        else:
                            safe_len = len(buf) - len(boundary_bytes) - 2
                            if safe_len > 0:
                                current_file.write(buf[:safe_len])
                                buf = buf[safe_len:]
                            break

            if bytes_read < length:
                if current_file:
                    current_file.close()
                    current_file = None
                if current_dest and current_dest.exists():
                    try:
                        current_dest.unlink()
                    except OSError:
                        pass
                publish_aborted()
                return

            if current_file:
                current_file.close()
                current_file = None
            if current_dest and current_dest.exists():
                try:
                    current_dest.unlink()
                except OSError:
                    pass
                current_dest = None

            publish_progress(force=True)
            self._respond(200, "application/json", json.dumps({"saved": saved}).encode())

            finished = True
            broker.publish(
                "clients",
                "upload_completed",
                {
                    **transfer_payload(100.0, "completed"),
                    "files": saved,
                },
            )
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            if current_file:
                try:
                    current_file.close()
                except OSError:
                    pass
                current_file = None
            if current_dest and current_dest.exists() and current_dest.name not in saved:
                try:
                    current_dest.unlink()
                except OSError:
                    pass
            publish_aborted()
            raise
        except Exception:
            if not finished:
                publish_aborted()
            raise

    def _respond_json(self, code, payload, headers=None):
        self._respond(
            code,
            "application/json",
            json.dumps(payload).encode("utf-8"),
            headers=headers,
        )

    def _respond(self, code, ctype, body, headers=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _not_found(self):
        self._respond(404, "text/plain", b"Not found")
