@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0."

REM Live microphone level meter.
REM Opens every input device at once and shows their levels side by side,
REM so you can just talk and see which one actually picks up your voice.
REM Keep this file ASCII-only; all Chinese text comes from mic_level.py.

if not exist "%~dp0debug" mkdir "%~dp0debug"
set "DIAG=%~dp0debug\launcher_log.txt"

echo ==== voice_tap mic_level launcher ==== > "%DIAG%"
echo [time] %DATE% %TIME% >> "%DIAG%"
echo [env] script dir = %~dp0 >> "%DIAG%"

echo [find] where python >> "%DIAG%"
where python >> "%DIAG%" 2>&1
echo [find] where py >> "%DIAG%"
where py >> "%DIAG%" 2>&1

set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY where py >nul 2>nul && set "PY=py -3"
echo [find] selected PY = [%PY%] >> "%DIAG%"

if not defined PY goto nopython

echo [run] %PY% tools\mic_level.py >> "%DIAG%"
%PY% "%~dp0tools\mic_level.py" %*
set "RC=%ERRORLEVEL%"
echo [run] exit code = %RC% >> "%DIAG%"
goto done

:nopython
echo [!!] Python not found in PATH >> "%DIAG%"
type "%DIAG%"
echo.
echo   [!!] Python not found. Install Python and tick "Add Python to PATH".
set "RC=1"

:done
echo.
echo ============================================================
echo   exit code = %RC%
echo ============================================================
echo.
pause
exit /b %RC%
