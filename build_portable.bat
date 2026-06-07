@echo off
setlocal enabledelayedexpansion

:: Switch to the folder containing this .bat
pushd "%~dp0"

echo =======================================================
echo   Video Dialogue HUD - Build Script
echo =======================================================
echo.

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Install Python and add it to PATH.
    pause & exit /b 1
)

:: Download yolov8n.pt if missing (~6 MB)
if not exist "yolov8n.pt" (
    echo [ASSET] Downloading yolov8n.pt ...
    python -c "import urllib.request as r; r.urlretrieve(\"https://github.com/ultralytics/assets/releases/latest/download/yolov8n.pt\", \"yolov8n.pt\"); print(\"  OK\")"
    if %errorlevel% neq 0 ( echo [ERROR] Download failed. & pause & exit /b 1 )
)

:: Download CJK font if missing (~18 MB, optional)
if not exist "NotoSansCJKtc-Bold.otf" (
    echo [ASSET] Downloading NotoSansCJKtc-Bold.otf ...
    python -c "import urllib.request as r; r.urlretrieve(\"https://github.com/googlefonts/noto-cjk/raw/main/Sans/OTF/TraditionalChinese/NotoSansCJKtc-Bold.otf\", \"NotoSansCJKtc-Bold.otf\"); print(\"  OK\")" 2>nul
    echo [INFO] Font done (failure is OK, app uses system font as fallback).
)

echo [1/5] Creating clean build virtualenv (.venv_pack) ...
if exist ".venv_pack" python -c "import shutil; shutil.rmtree('.venv_pack')"
python -m venv .venv_pack
if %errorlevel% neq 0 ( echo [ERROR] venv failed. & pause & exit /b 1 )

echo [2/5] Upgrading pip ...
call .venv_pack\Scripts\activate.bat
python -m pip install --upgrade pip --quiet

echo [3/5] Installing CPU-only PyTorch ...
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu --no-cache-dir --quiet
if %errorlevel% neq 0 ( echo [ERROR] PyTorch install failed. & pause & exit /b 1 )

echo [4/5] Installing app dependencies + PyInstaller ...
pip install pyinstaller customtkinter opencv-python ultralytics pandas openpyxl pillow numpy faster-whisper resemblyzer scikit-learn --quiet
if %errorlevel% neq 0 ( echo [ERROR] Dependency install failed. & pause & exit /b 1 )

echo [5/5] Running PyInstaller ...
pyinstaller --clean main.spec
if %errorlevel% neq 0 ( echo [ERROR] PyInstaller failed. See output above. & pause & exit /b 1 )

echo.
echo =======================================================
echo   Build complete!  Output: dist\
echo   NOTE: Copy ffmpeg.exe into dist\ before distributing.
echo =======================================================
echo.
popd
pause
