@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0."

REM This launcher only logs the environment diagnostics.
REM probe.py writes its own full output to debug\probe_<timestamp>\console.log,
REM so we do NOT redirect here - that way the microphone calibration prompts
REM stay visible on screen in real time.
REM Keep this file ASCII-only; all Chinese text comes from probe.py.

if not exist "%~dp0debug" mkdir "%~dp0debug"
set "DIAG=%~dp0debug\launcher_log.txt"

echo ==== voice_tap probe launcher ==== > "%DIAG%"
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

REM --asr also runs a speech recognition self-test.
REM First run downloads a ~480MB model; later runs use the cache.
echo [run] %PY% tools\probe.py --asr %* >> "%DIAG%"
%PY% "%~dp0tools\probe.py" --asr %*
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
echo   full output saved under debug\probe_^(timestamp^)
echo ============================================================
echo.
pause
exit /b %RC%
