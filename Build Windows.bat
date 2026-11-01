@echo off
set PYTHONUTF8=1
setlocal
cd /d "%~dp0"
py -3.12 -m venv .venv-build
if errorlevel 1 goto failed
.venv-build\Scripts\python.exe -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto failed
set QT_QPA_PLATFORM=offscreen
.venv-build\Scripts\python.exe -m unittest discover -s tests -v
if errorlevel 1 goto failed
set QT_QPA_PLATFORM=
.venv-build\Scripts\python.exe -m PyInstaller --noconfirm --windowed --name LocalizationQA --collect-all keyring run.py
if errorlevel 1 goto failed
echo Build complete: dist\LocalizationQA\LocalizationQA.exe
pause
exit /b 0
:failed
echo Build failed. Install Python 3.12 and check the error above.
pause
exit /b 1
