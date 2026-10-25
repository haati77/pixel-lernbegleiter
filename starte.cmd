@echo off
rem Pixel starten: Gesprächsprogramm und Handy-Oberfläche. Doppelklick genügt.
rem Weitere Optionen werden durchgereicht, z. B.: starte.cmd --nur-lokal
cd /d "%~dp0"
"venv\Scripts\python.exe" starte.py %*
pause
