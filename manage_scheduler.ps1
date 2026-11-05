[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet("install", "start", "pause", "resume", "status", "remove", "help")]
    [string]$Action = "help",

    [string]$TaskName = "AutoVideoAgent_AllChannels"
)

$VbsPath = "C:\learning\Agents\videos automation\run_agent_silent.vbs"

function Show-Help {
    Write-Host "============================================================"
    Write-Host " Windows Task Scheduler Manager: $TaskName"
    Write-Host "============================================================"
    Write-Host "Usage: .\manage_scheduler.ps1 [Action]"
    Write-Host ""
    Write-Host "Actions:"
    Write-Host "  install   Register task to run silently daily at 11:00 AM"
    Write-Host "  pause     Pause automatic daily runs (disables trigger)"
    Write-Host "  resume    Resume automatic daily runs (enables trigger)"
    Write-Host "  start     Run the agent immediately in the background"
    Write-Host "  status    Show current task status (Ready, Disabled, Running)"
    Write-Host "  remove    Completely delete task from Windows Task Scheduler"
    Write-Host "============================================================"
}

switch ($Action) {
    "install" {
        $actionObj = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$VbsPath`""
        $triggerObj = New-ScheduledTaskTrigger -Daily -At "11:00 AM"
        $settingsObj = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

        Register-ScheduledTask -TaskName $TaskName -Action $actionObj -Trigger $triggerObj -Settings $settingsObj -Force | Out-Null
        Write-Host "[+] Registered '$TaskName' to run daily at 11:00 AM." -ForegroundColor Green
    }
    "start" {
        $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if ($task) {
            Start-ScheduledTask -TaskName $TaskName
            Write-Host "[*] Triggered '$TaskName'. Running in background." -ForegroundColor Green
            Write-Host "    Check 'output\agent_runner.log' for progress." -ForegroundColor Cyan
        } else {
            Write-Host "[-] Task '$TaskName' not found. Run '.\manage_scheduler.ps1 install' first." -ForegroundColor Red
        }
    }
    "pause" {
        $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if ($task) {
            Disable-ScheduledTask -TaskName $TaskName | Out-Null
            Write-Host "[||] Paused '$TaskName'. Automatic 11:00 AM runs are now DISABLED." -ForegroundColor Yellow
        } else {
            Write-Host "[-] Task '$TaskName' not found." -ForegroundColor Red
        }
    }
    "resume" {
        $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if ($task) {
            Enable-ScheduledTask -TaskName $TaskName | Out-Null
            Write-Host "[>] Resumed '$TaskName'. Will fire daily at 11:00 AM." -ForegroundColor Green
        } else {
            Write-Host "[-] Task '$TaskName' not found." -ForegroundColor Red
        }
    }
    "status" {
        $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if ($task) {
            [PSCustomObject]@{
                TaskName = $task.TaskName
                State    = $task.State
            } | Format-Table -AutoSize
        } else {
            Write-Host "[-] Task '$TaskName' is NOT currently registered." -ForegroundColor DarkGray
        }
    }
    "remove" {
        $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if ($task) {
            Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
            Write-Host "[x] Removed '$TaskName' from Windows Task Scheduler." -ForegroundColor Green
        } else {
            Write-Host "[-] Task '$TaskName' was already removed or not found." -ForegroundColor DarkGray
        }
    }
    default {
        Show-Help
    }
}
