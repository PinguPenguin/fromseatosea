@echo off
setlocal
cd /d "%~dp0.."
python "tools\c2c_tag_reshuffle_tool.py" %*
