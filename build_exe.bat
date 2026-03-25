@echo off
setlocal

cd /d "%~dp0"

echo [1/3] Aggiorno pip...
py -m pip install --upgrade pip
if errorlevel 1 goto :error

echo [2/3] Installo/aggiorno PyInstaller...
py -m pip install --upgrade pyinstaller
if errorlevel 1 goto :error

echo [3/3] Creo eseguibile...
py -m PyInstaller --clean --noconfirm --onefile --windowed --name MindTrailDemo --add-data "questions;questions" mindtrail_demo.py
if errorlevel 1 goto :error

echo.
echo Build completata.
echo Eseguibile: dist\MindTrailDemo.exe
goto :end

:error
echo.
echo Errore durante la build.
exit /b 1

:end
endlocal
