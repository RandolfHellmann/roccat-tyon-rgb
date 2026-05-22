@echo off
REM Convenience launcher: forwards all args to tyon_rgb.py inside the venv
"%~dp0.venv\Scripts\python.exe" "%~dp0tyon_rgb.py" %*
