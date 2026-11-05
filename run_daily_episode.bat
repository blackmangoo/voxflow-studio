@echo off
cd /d "C:\learning\Agents\videos automation"
call "venv\Scripts\activate.bat"

echo ============================================================
echo  AUTONOMOUS AI VIDEO AGENT - DAILY RUN - %DATE% %TIME%
echo ============================================================

echo Generating BODY SIMULATOR episode (ENGLISH ONLY)...
python multi_channel_agent.py --channel body_simulator --lang english >> "output\agent_runner.log" 2>&1

echo ============================================================
echo  COMPLETE - %TIME%
echo ============================================================
