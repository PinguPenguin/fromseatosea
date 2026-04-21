@echo off
setlocal
cd /d "%~dp0.."
python "%~dp0c2c_tag_reshuffle_tool.py" %*
