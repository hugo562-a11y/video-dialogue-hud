import atexit
import os
import random
import shutil
import string
import tempfile

APP_TITLE = "影片對話 HUD 工具"
MODEL_PATH = "yolov8n.pt"
FONT_NAME = "NotoSansCJKtc-Bold.otf"
MAX_PREVIEW_SIZE = 720
SILENCE_SPEAKER = "無講話"
SILENCE_TEXT = "（無講話）"
MIN_SILENCE_SECONDS = 0.45

# 專案根目錄（core/ 的上一層）
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_SAFE_PATH_MAP: dict = {}
_CLEANUP_PATHS: list = []


def get_safe_path(path: str) -> str:
    """給 OpenCV/ffmpeg 一個純 ASCII 路徑；原路徑含非 ASCII 時建立符號連結或複製。"""
    if not path:
        return path
    if path in _SAFE_PATH_MAP:
        return _SAFE_PATH_MAP[path]
    try:
        path.encode("ascii")
        return path
    except UnicodeEncodeError:
        ext = os.path.splitext(path)[1]
        safe_name = "".join(random.choices(string.ascii_letters, k=12)) + ext
        safe_path = os.path.join(tempfile.gettempdir(), safe_name)
        try:
            os.link(path, safe_path)
        except Exception:
            shutil.copy2(path, safe_path)
        _SAFE_PATH_MAP[path] = safe_path
        _CLEANUP_PATHS.append(safe_path)
        return safe_path


@atexit.register
def cleanup_temp_files() -> None:
    for path in _CLEANUP_PATHS:
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass
