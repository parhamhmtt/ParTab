import socketserver
import sys
import threading
import time
import webbrowser

from . import state
from .handler import Handler
from .paths import UPLOAD_DIR


class ParTabThreadingServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]

        if isinstance(exc, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)):
            return

        if isinstance(exc, OSError) and getattr(exc, "winerror", None) in {10053, 10054}:
            return

        super().handle_error(request, client_address)


def main():
    state.url = f"http://{state.ip}:{state.port}"
    webbrowser.open(f"http://localhost:{state.port}")
    print()
    print("  ╔══════════════════════════════════════╗")
    print("               ParTab  🚀              ")
    print("  ╠══════════════════════════════════════╣")
    print(f"  ║ Local  →  http://localhost:{state.port}      ║")
    print(f"  ║ Mobile →  {state.url:<27}║")
    print("  ╠══════════════════════════════════════╣")
    print("  ║  Open the Mobile URL on your iPhone  ║")
    print("  ║  (same Wi-Fi required)               ║")
    print("  ╚══════════════════════════════════════╝")
    print()
    print(f"  Uploads saved to: {UPLOAD_DIR}")
    print("  Press Ctrl+C to stop.\n")
    with ParTabThreadingServer(("", state.port), Handler) as httpd:
        def heartbeat_monitor():
            while state.last_ping[0] is None:
                time.sleep(1)
            print("  ✔  PC tab connected — watching for disconnect.")
            while True:
                time.sleep(2)
                if time.time() - state.last_ping[0] > 90:
                    print("  🛑  Tab closed — shutting down.")
                    httpd.shutdown()
                    return

        threading.Thread(target=heartbeat_monitor, daemon=True).start()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n  Server stopped.")
        else:
            print("  ✔  ParTab server stopped.")
