@echo off
rem Builds dist\Telestep.exe (one file, no console). Needs:  pip install pyinstaller
rem Add --uac-admin to the line below if you always want it to start elevated (records admin windows).
cd /d "%~dp0"
pyinstaller --onefile --windowed --name Telestep --icon assets\telestep.ico ^
  --collect-all uiautomation --collect-data docx --collect-data reportlab ^
  --add-data "HELP.md;." --add-data "LICENSE;." --add-data "THIRD_PARTY_NOTICES.md;." ^
  --add-data "assets\telestep_logo_256.png;assets" --add-data "assets\telestep_icon_64.png;assets" ^
  --hidden-import telestep_help ^
  --hidden-import telestep_review --hidden-import telestep_report --hidden-import telestep_widgets --hidden-import telestep_settings ^
  telestep.py
echo.
echo Done: dist\Telestep.exe   (GUI only; use python telestep_recorder.py for the command line)
