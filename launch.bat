@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"

:: Check Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    powershell -Command "Add-Type -AssemblyName PresentationFramework; [System.Windows.MessageBox]::Show('Python not found.  Please install Python 3.10+ from python.org and check Add Python to PATH.', 'Missing Python', 'OK', 'Error')" >nul 2>&1
    if %errorlevel% neq 0 (
        echo Python not found. Install from https://www.python.org/downloads/
        pause
    )
    exit /b 1
)

:: Python finds its own pythonw.exe; cwd is already set by the cd above
python -c "import sys,os,subprocess; d=os.path.dirname(sys.executable); pyw=os.path.join(d,'pythonw.exe'); exe=pyw if os.path.exists(pyw) else sys.executable; subprocess.Popen([exe,'launcher.py'])"
