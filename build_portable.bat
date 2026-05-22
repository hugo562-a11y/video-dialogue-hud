@echo off
chcp 65001 >nul
echo ===================================================
echo   影片對話 HUD 工具 — 獨立可攜式打包程序 (CPU 最佳化版)
echo ===================================================
echo.

:: 檢查 Python 是否已安裝
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [錯誤] 找不到 Python！請確保已安裝 Python 並且加入了系統環境變數 PATH。
    pause
    exit /b 1
)

:: 檢查 ffmpeg.exe 是否在根目錄
if not exist "ffmpeg.exe" (
    echo [警告] 找不到 ffmpeg.exe！
    echo 語音辨識與對齊功能需要 ffmpeg。
    echo 請前往 https://github.com/BtbN/FFmpeg-Builds/releases 下載 ffmpeg-master-latest-win64-gpl.zip,
    echo 解壓後將 bin 目錄下的 ffmpeg.exe 複製到此專案目錄（z:\!影片追踪工具\）中。
    echo.
    set /p choice="是否仍要繼續打包 (沒有 ffmpeg.exe 將無法進行語音時間軸校正)？[Y/N]: "
    if /i "%choice%" neq "y" exit /b 1
)

echo [1/5] 正在建立獨立且乾淨的打包專用虛擬環境 (.venv_pack)...
if exist ".venv_pack" (
    echo [提示] 偵測到已存在的 .venv_pack，正在清理舊檔案...
    rmdir /s /q .venv_pack
)
python -m venv .venv_pack
if %errorlevel% neq 0 (
    echo [錯誤] 建立虛擬環境失敗！
    pause
    exit /b 1
)

echo [2/5] 啟用虛擬環境並升級 pip...
call .venv_pack\Scripts\activate.bat
python -m pip install --upgrade pip

echo [3/5] 正在安裝 CPU 版本 PyTorch (關鍵：縮減體積至 150MB)...
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu --no-cache-dir
if %errorlevel% neq 0 (
    echo [錯誤] 安裝 PyTorch (CPU) 失敗！
    pause
    exit /b 1
)

echo [4/5] 正在安裝應用程式相依套件與打包工具...
pip install pyinstaller customtkinter opencv-python ultralytics pandas openpyxl pillow numpy faster-whisper resemblyzer scikit-learn
if %errorlevel% neq 0 (
    echo [錯誤] 套件安裝失敗，請檢查網路連線或套件名稱。
    pause
    exit /b 1
)

echo [5/5] 開始使用 PyInstaller 進行封裝...
if exist "dist\影片對話HUD工具" (
    echo 正在清理舊有的 dist 目錄...
    rmdir /s /q "dist\影片對話HUD工具"
)
pyinstaller --clean main.spec
if %errorlevel% neq 0 (
    echo [錯誤] PyInstaller 打包失敗！請檢查上面的錯誤訊息。
    pause
    exit /b 1
)

echo.
echo ===================================================
echo   恭喜！獨立程式資料夾編譯成功！
echo   輸出路徑: z:\!影片追踪工具\dist\影片對話HUD工具\
echo ===================================================
echo.
echo 接下來，您可以使用 Inno Setup 編譯 installer.iss，
echo 即可生成單一的 Setup.exe 安裝程式！
echo.
pause
