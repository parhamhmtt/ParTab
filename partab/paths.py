from pathlib import Path
import sys


BASE_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
UPLOAD_TMP_DIR = UPLOAD_DIR / ".partab_tmp"
UPLOAD_TMP_DIR.mkdir(exist_ok=True)


def resource_path(relative):
    base = getattr(sys, '_MEIPASS', BASE_DIR)
    return Path(base) / relative
