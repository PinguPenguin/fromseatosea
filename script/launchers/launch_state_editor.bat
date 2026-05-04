@echo off
setlocal
cd /d "%~dp0.."
python "tools\vic3_state_editor.py" %*
