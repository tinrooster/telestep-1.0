@echo off
rem Starts the toolbar without a console window. Right-click > Run as administrator to record admin apps.
cd /d "%~dp0"
start "" pythonw telestep.py
