@echo off
rem Builds dist\Telestep.exe (one file, no console). Needs:  pip install pyinstaller
rem Add --uac-admin to the line below if you always want it to start elevated (records admin windows).
rem
rem For a smaller, repeatable build (and fewer antivirus flags) run this from a clean virtual environment holding only requirements.txt + pyinstaller. --noupx and --exclude-module keep UPX and unused packages (numpy, pandas, setuptools) out.
cd /d "%~dp0"
pyinstaller --onefile --windowed --name Telestep --icon assets\telestep.ico ^
  --noupx --exclude-module numpy --exclude-module pandas --exclude-module setuptools --exclude-module pkg_resources ^
  --collect-all uiautomation --collect-submodules pystray --hidden-import pystray._win32 --collect-data docx --collect-data reportlab ^
  --add-data "HELP.md;." --add-data "LICENSE;." --add-data "THIRD_PARTY_NOTICES.md;." ^
  --add-data "assets\telestep_logo_256.png;assets" --add-data "assets\telestep_icon_64.png;assets" ^
  --hidden-import telestep_help --hidden-import telestep_support ^
  --hidden-import telestep_review --hidden-import telestep_report --hidden-import telestep_widgets --hidden-import telestep_settings --hidden-import telestep_privacy --hidden-import telestep_marks --hidden-import telestep_update --hidden-import telestep_audio --hidden-import telestep_player ^
  telestep.py
echo.
echo Done: dist\Telestep.exe   (GUI only; use python telestep_recorder.py for the command line)
