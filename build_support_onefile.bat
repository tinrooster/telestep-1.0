@echo off
rem Builds dist\Telestep-Support.exe - ONE file, the same program, but it starts in Support mode (one-button recorder
rem that produces a ZIP for IT).  The "Support" in the file name is what selects the mode.  Needs:  pip install pyinstaller
rem Single-file builds are flagged by antivirus / SmartScreen more often than the folder build (build_support_exe.bat).
rem Put your help-desk details in telestep_support.json in this folder first (copy telestep_support.example.json);
rem keep that file in the same folder as the exe when you send it out.
cd /d "%~dp0"
pyinstaller --onefile --noconfirm --windowed --name Telestep-Support --icon assets\telestep.ico ^
  --collect-all uiautomation --collect-data docx --collect-data reportlab ^
  --add-data "HELP.md;." --add-data "LICENSE;." --add-data "THIRD_PARTY_NOTICES.md;." ^
  --add-data "assets\telestep_logo_256.png;assets" --add-data "assets\telestep_icon_64.png;assets" ^
  --hidden-import telestep_help --hidden-import telestep_support ^
  --hidden-import telestep_review --hidden-import telestep_report --hidden-import telestep_widgets --hidden-import telestep_settings ^
  telestep.py
if errorlevel 1 goto :fail
if exist telestep_support.json (copy /y telestep_support.json dist\telestep_support.json >nul) else (if not exist dist\telestep_support.json copy telestep_support.example.json dist\telestep_support.json >nul)
echo.
echo Done: dist\Telestep-Support.exe  + dist\telestep_support.json  (send both, in one folder)
echo SHA-256 of the exe:
powershell -NoProfile -Command "(Get-FileHash 'dist\Telestep-Support.exe' -Algorithm SHA256).Hash"
goto :eof

:fail
echo.
echo Build failed - see the messages above.
exit /b 1
