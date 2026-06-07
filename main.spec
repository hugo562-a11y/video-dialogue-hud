# -*- mode: python ; coding: utf-8 -*-
import os
import sys
import customtkinter

block_cipher = None

# 取得 customtkinter 的安裝路徑
customtkinter_path = os.path.dirname(customtkinter.__file__)

# 定義要打包打包的靜態資料夾與檔案
datas = [
    # CustomTkinter 必要的資源檔
    (os.path.join(customtkinter_path, "assets"), "customtkinter/assets"),
    (os.path.join(customtkinter_path, "themes"), "customtkinter/themes"),
    # 專案自身的靜態檔案
    ("yolov8n.pt", "."),
    ("NotoSansCJKtc-Bold.otf", "."),
]

# ffmpeg.exe 必須存在才能打包（由 build_portable.bat 自動下載）
if not os.path.exists("ffmpeg.exe"):
    raise SystemExit(
        "\n[ERROR] ffmpeg.exe not found in project root.\n"
        "Run build_portable.bat — it will download ffmpeg automatically.\n"
    )
datas.append(("ffmpeg.exe", "."))

# 隱式匯入 (確保 PyInstaller 抓得到動態載入的套件)
hiddenimports = [
    "torch",
    "numpy",
    "pandas",
    "cv2",
    "PIL",
    "customtkinter",
    "faster_whisper",
    "resemblyzer",
    "sklearn",
    "sklearn.cluster",
    "openpyxl",
    "ultralytics",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "notebook", "jedi", "IPython"],  # 排除不必要的超大套件
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# 採用目錄打包模式 (--onedir)，因為 PyTorch 與 YOLO 模型太大，
# 單一檔案模式 (--onefile) 會導致每次啟動都需要解壓縮 30 秒以上，體驗極差。
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="影片對話HUD工具",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,                  # 設為 False 表示為無控制台視窗 (GUI 模式)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="talking.png" if os.path.exists("talking.png") else None, # 如果有圖示可以放在這裡
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="影片對話HUD工具",
)
