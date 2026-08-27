@echo off
cd /d "%~dp0"
py rb5_ui.py
if errorlevel 1 pause
