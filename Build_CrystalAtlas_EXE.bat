@echo off
setlocal
cd /d "%~dp0"

echo Installing build requirements...
py -m pip install --upgrade pip
py -m pip install -r requirements.txt
if errorlevel 1 goto :error

echo Building CrystalAtlas.exe...
py -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --windowed ^
  --name "CrystalAtlas" ^
  --icon "crystalatlas_icon.ico" ^
  --add-data "crystalatlas_icon.ico;." ^
  --add-data "crystalatlas_logo.png;." ^
  "CrystalAtlas.py"

if errorlevel 1 goto :error
echo.
echo Finished:
echo %~dp0dist\CrystalAtlas.exe
pause
exit /b 0

:error
echo.
echo Build failed. Copy the complete error text for troubleshooting.
pause
exit /b 1
