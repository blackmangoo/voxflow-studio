@echo off
echo =======================================================
echo   REGISTERING AUTONOMOUS VIDEO AGENT IN WINDOWS SCHEDULER
echo =======================================================
echo.
echo Task Name: AutoVideoAgent_OrganComedy
echo Schedule: Daily at 11:00 AM
echo Target: C:\learning\Agents\videos automation\run_agent_silent.vbs
echo.

schtasks /create /tn "AutoVideoAgent_OrganComedy" /tr "wscript.exe \"C:\learning\Agents\videos automation\run_agent_silent.vbs\"" /sc daily /st 11:00 /f

if %ERRORLEVEL% equ 0 (
    echo.
    echo [SUCCESS] Windows Task successfully created!
    echo Your laptop will now automatically generate a new video every day at 11:00 AM.
    echo You can check or change the time in Windows Task Scheduler at any time.
) else (
    echo.
    echo [NOTE] If you saw an 'Access Denied' message, please Right-Click setup_scheduler.bat and select 'Run as Administrator'.
)
echo.
pause
