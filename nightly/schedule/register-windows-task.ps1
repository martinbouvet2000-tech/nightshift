# Register the nightshift runner as a Windows scheduled task (runs as the current user).
# Usage (PowerShell 5.1+ or 7):
#   powershell -NoProfile -ExecutionPolicy Bypass -File register-windows-task.ps1 -Vault "D:\notes" [-Time 05:30] [-TaskName Nightshift]
# Remove with: Unregister-ScheduledTask -TaskName Nightshift -Confirm:$false
# ASCII only: Windows PowerShell 5.1 reads scripts without a BOM as ANSI.
param(
  [Parameter(Mandatory = $true)][string]$Vault,
  [string]$Time = '05:30',
  [string]$TaskName = 'Nightshift',
  [string]$Node = '',
  [switch]$Backup
)
$ErrorActionPreference = 'Stop'
if (-not $Node) { $Node = (Get-Command node -ErrorAction Stop).Source }
$runner = (Resolve-Path (Join-Path $PSScriptRoot '..\runner.mjs')).Path
$vaultPath = (Resolve-Path $Vault).Path
$taskArgs = "`"$runner`" --vault `"$vaultPath`""
if ($Backup) { $taskArgs += ' --backup' }

$action   = New-ScheduledTaskAction -Execute $Node -Argument $taskArgs -WorkingDirectory (Split-Path $runner)
$trigger  = New-ScheduledTaskTrigger -Daily -At $Time
# WakeToRun: wake the PC from sleep. StartWhenAvailable: catch up a run missed while the PC was off.
# 1 h limit covers 18 min + 20 min retry wait + 18 min.
$settings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 1) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
  -Description 'nightshift: nightly vault consolidation with Claude Code' -Force | Out-Null
Write-Host "Registered task '$TaskName' daily at $Time -> $Node $taskArgs"
Write-Host "Test it now with: Start-ScheduledTask -TaskName $TaskName"
