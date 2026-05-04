@echo off
setlocal
cd /d "%~dp0.."
python "tools\c2c_province_shape_tool.py" %*
