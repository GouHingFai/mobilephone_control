@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0."

REM voice_tap main launcher.
REM Keep this file ASCII-only; all Chinese text comes from voice_tap/main.py.
REM
REM Useful flags (append after run.bat):
REM   --dump     check screen parsing only, no speech, no clicking
REM   --preview  do not really tap, draw a marker on a screenshot instead
REM   --once     handle a single utterance then exit
REM   --device N force a microphone
REM
REM NOTE: this file MUST use CRLF line endings. With LF-only endings cmd.exe
REM can abort the script before it reaches anything, closing the window instantly.

if not exist "%~dp0debug" mkdir "%~dp0debug"
set "DIAG=%~dp0debug\launcher_log.txt"

echo ==== voice_tap launcher ==== > "%DIAG%"
echo [time] %DATE% %TIME% >> "%DIAG%"
echo [env] script dir = %~dp0 >> "%DIAG%"
echo [env] cwd        = %CD% >> "%DIAG%"

echo [find] where python >> "%DIAG%"
where python >> "%DIAG%" 2>&1
echo [find] where py >> "%DIAG%"
where py >> "%DIAG%" 2>&1

set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY where py >nul 2>nul && set "PY=py -3"
echo [find] selected PY = [%PY%] >> "%DIAG%"

if not defined PY goto nopython

set "PYTHONPATH=%~dp0"
set "PYTHONIOENCODING=utf-8"
echo [run] %PY% -m voice_tap.main %* >> "%DIAG%"
%PY% -m voice_tap.main %*
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
