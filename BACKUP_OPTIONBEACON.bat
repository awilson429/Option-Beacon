@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo  OptionBeacon Samsung T5 Backup and Disaster Recovery
echo ============================================================
echo.

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\backup_optionbeacon.ps1" %*
set "BACKUP_EXIT_CODE=%ERRORLEVEL%"

echo.
if not defined OPTIONBEACON_BACKUP_NO_PAUSE pause
exit /b %BACKUP_EXIT_CODE%
