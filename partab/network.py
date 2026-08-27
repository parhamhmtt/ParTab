import socket

import psutil

from . import state


def initialize_network():
    state.ip = get_local_ipv4()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as test:
        test.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            test.bind(("", state.port))
        except OSError:
            print(f"\n⚠ Port {state.port} is already in use.")

            if not kill_port(state.port):
                state.port = find_free_port(state.port + 1)

    state.url = f"http://{state.ip}:{state.port}"


def get_local_ipv4() -> str:
    try:
        for iface, addrs in psutil.net_if_addrs().items():
            name = iface.lower()
            if any(x in name for x in (
                    "wi-fi",
                    "wifi",
                    "wireless",
                    "wlan",
                    "wlp",
                    "wlo",
                    "wl"
            )):
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
