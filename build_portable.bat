@echo off
setlocal enabledelayedexpansion

:: Switch to the folder containing this .bat
pushd "%~dp0"

echo =======================================================
echo   Video Dialogue HUD - Portable Build Script
echo =======================================================
echo.

:: ?? 0. Prerequisites ????????????????????????????????????

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Install Python and add it to PATH.
    pause & exit /b 1
)

:: Download yolov8n.pt if missing (~6 MB)
if not exist "yolov8n.pt" (
    echo [ASSET] Downloading yolov8n.pt ...
    python -c "import urllib.request as r; r.urlretrieve(\"https://github.com/ultralytics/assets/releases/latest/download/yolov8n.pt\", \"yolov8n.pt\"); print(\"  yolov8n.pt OK\")"
    if %errorlevel% neq 0 ( echo [ERROR] Download failed. & pause & exit /b 1 )
)

:: Download CJK font if missing (~18 MB, optional)
if not exist "NotoSansCJKtc-Bold.otf" (
    echo [ASSET] Downloading NotoSansCJKtc-Bold.otf ...
    python -c "import urllib.request as r; r.urlretrieve(\"https://github.com/googlefonts/noto-cjk/raw/main/Sans/OTF/TraditionalChinese/NotoSansCJKtc-Bold.otf\", \"NotoSansCJKtc-Bold.otf\"); print(\"  Font OK\")" 2>nul
    echo [INFO] Font done (failure is OK, app uses system font as fallback).
)

:: NOTE: ffmpeg.exe is NOT bundled. Users download it themselves.
:: If ffmpeg.exe exists here it will be included; otherwise users place it next to the exe.

:: ?? 1. Build virtualenv ?????????????????????????????????

echo [1/6] Creating clean build virtualenv (.venv_pack) ...
if exist ".venv_pack" python -c "import shutil; shutil.rmtree('.venv_pack')"
python -m venv .venv_pack
if %errorlevel% neq 0 ( echo [ERROR] venv failed. & pause & exit /b 1 )

:: ?? 2. Pip ?????????????????????????????????????????????

echo [2/6] Upgrading pip ...
call .venv_pack\Scripts\activate.bat
python -m pip install --upgrade pip --quiet

:: ?? 3. PyTorch (CPU) ???????????????????????????????????

echo [3/6] Installing CPU-only PyTorch ...
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu --no-cache-dir --quiet
if %errorlevel% neq 0 ( echo [ERROR] PyTorch install failed. & pause & exit /b 1 )

:: ?? 4. Dependencies ????????????????????????????????????

echo [4/6] Installing app dependencies + PyInstaller ...
pip install pyinstaller customtkinter opencv-python ultralytics pandas openpyxl pillow numpy faster-whisper resemblyzer scikit-learn --quiet
if %errorlevel% neq 0 ( echo [ERROR] Dependency install failed. & pause & exit /b 1 )

:: ?? 5. PyInstaller ?????????????????????????????????????

echo [5/6] Running PyInstaller ...
pyinstaller --clean main.spec
if %errorlevel% neq 0 ( echo [ERROR] PyInstaller failed. See output above. & pause & exit /b 1 )

:: ?? 6. Zip ?????????????????????????????????????????????

echo [6/6] Creating portable zip ...
python -c "import shutil,os; d=[f for f in os.listdir('dist') if os.path.isdir(os.path.join('dist',f))]; shutil.make_archive('VideoDialogueHUD_portable','zip','dist',d[0]); print('  Zip OK: VideoDialogueHUD_portable.zip')"
if %errorlevel% neq 0 ( echo [ERROR] Zip failed. & pause & exit /b 1 )

echo.
echo =======================================================
echo   Build complete!
echo   Portable zip : VideoDialogueHUD_portable.zip
echo   REMINDER     : Users must download ffmpeg.exe separately.
echo   See README for the ffmpeg download link.
echo =======================================================
echo.
popd
pause
