@echo off
rem Builds the Support-mode package:  dist\Telestep-Support.zip  (a folder with Telestep-Support.exe, its settings file
rem and a short read-me).  Needs:  pip install pyinstaller
rem
rem Your settings: put your help-desk details in telestep_support.json in THIS folder (copy telestep_support.example.json
rem and edit it).  If it isn't there, the example is used.  The file is copied into the package.
rem
rem Why a folder (--onedir) and not one exe: a single self-extracting exe is flagged by antivirus / SmartScreen far more
rem often.  The user extracts the zip and runs Telestep-Support.exe.  The "Support" in the name selects Support mode.
cd /d "%~dp0"
set NAME=Telestep-Support
if exist "dist\%NAME%" rmdir /s /q "dist\%NAME%"
if exist "dist\%NAME%.zip" del /q "dist\%NAME%.zip"

pyinstaller --onedir --noconfirm --windowed --name %NAME% --icon assets\telestep.ico ^
  --collect-all uiautomation --collect-data docx --collect-data reportlab ^
  --add-data "HELP.md;." --add-data "LICENSE;." --add-data "THIRD_PARTY_NOTICES.md;." ^
  --add-data "assets\telestep_logo_256.png;assets" --add-data "assets\telestep_icon_64.png;assets" ^
  --hidden-import telestep_help --hidden-import telestep_support ^
  --hidden-import telestep_review --hidden-import telestep_report --hidden-import telestep_widgets --hidden-import telestep_settings ^
  telestep.py
if errorlevel 1 goto :fail

if exist telestep_support.json (copy /y telestep_support.json "dist\%NAME%\telestep_support.json" >nul) else (copy /y telestep_support.example.json "dist\%NAME%\telestep_support.json" >nul)
(
  echo Telestep Support - how to use
  echo.
  echo 1. Extract ALL of this zip first ^(right-click the zip, "Extract All"^). Do not run it from inside the zip.
  echo 2. Open the extracted folder and double-click Telestep-Support.exe.
  echo 3. Click Record, do the steps that cause the problem, then click Stop.
  echo 4. A new ZIP appears on your Desktop. Send that ZIP to IT.
  echo.
  echo Nothing is uploaded or sent anywhere by this program.
) > "dist\%NAME%\READ ME FIRST.txt"

powershell -NoProfile -Command "Compress-Archive -Path 'dist\%NAME%' -DestinationPath 'dist\%NAME%.zip' -Force"
if errorlevel 1 goto :fail
echo.
echo Done: dist\%NAME%.zip
echo SHA-256 (publish this next to the download link so people can check it):
powershell -NoProfile -Command "(Get-FileHash 'dist\%NAME%.zip' -Algorithm SHA256).Hash"
echo.
echo Test it: extract the zip to a new folder and run Telestep-Support.exe from there.
goto :eof

:fail
echo.
echo Build failed - see the messages above.
exit /b 1
