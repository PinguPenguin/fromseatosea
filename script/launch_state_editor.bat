@echo off
setlocal
cd /d "%~dp0.."
python "%~dp0vic3_state_editor.py" %*
