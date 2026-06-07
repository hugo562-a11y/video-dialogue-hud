"""影片對話 HUD 工具 — 入口點。"""
import os
import sys

# 如果是打包後的獨立 EXE 執行檔，自動將執行檔目錄加入 PATH，以尋找同目錄下的 ffmpeg.exe 等工具
if getattr(sys, "frozen", False):
    _app_dir = os.path.dirname(sys.executable)
    if _app_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _app_dir + os.pathsep + os.environ["PATH"]

try:
    import tqdm
    tqdm.tqdm.monitor_interval = 0
except Exception:
    pass

try:
    import torch
    _torch_lib = os.path.dirname(torch.__file__)
    _nvidia_dir = os.path.join(os.path.dirname(_torch_lib), "nvidia")
    if os.path.exists(_nvidia_dir):
        for _folder in os.listdir(_nvidia_dir):
            # Skip cudnn — torch already bundles its own cuDNN in torch/lib.
            # Adding the pip nvidia-cudnn-cu12 bin dir causes DLL version mismatch
            # (cudnn64_9.dll filename is shared; sub-libraries end up from different versions).
            if _folder == "cudnn":
                continue
            _bin = os.path.join(_nvidia_dir, _folder, "bin")
            if os.path.exists(_bin) and _bin not in os.environ.get("PATH", ""):
                os.environ["PATH"] = _bin + os.pathsep + os.environ["PATH"]
except Exception:
    pass

from ui.app import App

if __name__ == "__main__":
    App().mainloop()


