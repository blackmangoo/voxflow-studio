@echo off
cd /d "C:\learning\Agents\videos automation"
call "venv\Scripts\activate.bat"
python accounts\check_quotas.py
pause
