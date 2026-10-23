@echo off
rem Builds dist\Telestep-Support.exe - the same program, but it starts in Support mode (one-button recorder that
rem produces a ZIP for IT).  The "Support" in the file name is what selects the mode.  Needs:  pip install pyinstaller
rem Edit dist\telestep_support.json (copied from the example) to set your help-desk contact, size limit, etc.;
rem keep it in the same folder as the exe when you send it out.
cd /d "%~dp0"
pyinstaller --onefile --windowed --name Telestep-Support --icon assets\telestep.ico ^
  --collect-all uiautomation --collect-data docx --collect-data reportlab ^
  --add-data "HELP.md;." --add-data "LICENSE;." --add-data "THIRD_PARTY_NOTICES.md;." ^
  --add-data "assets\telestep_logo_256.png;assets" --add-data "assets\telestep_icon_64.png;assets" ^
  --hidden-import telestep_help --hidden-import telestep_support ^
  --hidden-import telestep_review --hidden-import telestep_report --hidden-import telestep_widgets --hidden-import telestep_settings ^
  telestep.py
if not exist dist\telestep_support.json copy telestep_support.example.json dist\telestep_support.json >nul
echo.
echo Done: dist\Telestep-Support.exe  + dist\telestep_support.json  (send both, in one folder)
