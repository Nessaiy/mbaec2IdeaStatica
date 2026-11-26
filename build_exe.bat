@echo off
rem Baut pdf2idea.exe (eine einzelne Datei, laeuft ohne Installation / ohne Admin).
rem Voraussetzung: Python 3.10+ auf diesem PC (Benutzer-Installation genuegt).
cd /d "%~dp0"
python -m venv .venv || goto :err
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt || goto :err
python -c "import datetime;open('pdf2idea/_build.py','w').write('BUILD = ' + repr(datetime.datetime.now().strftime('%%d.%%m.%%Y %%H:%%M')))"
python -m PyInstaller --noconfirm --clean --onefile --windowed --icon pdf2idea\icon.ico --name pdf2idea run.py || goto :err
echo.
echo Fertig: dist\pdf2idea.exe  (diese eine Datei auf den Terminalserver kopieren)
pause
exit /b 0
:err
echo FEHLER beim Bauen.
pause
exit /b 1
