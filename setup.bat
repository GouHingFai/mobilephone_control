@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0."

if not exist "%~dp0debug" mkdir "%~dp0debug"
set "LOG=%~dp0debug\launcher_log.txt"

echo ==== voice_tap setup launcher ==== > "%LOG%"
echo [time] %DATE% %TIME% >> "%LOG%"
echo [env] script dir = %~dp0 >> "%LOG%"
echo [env] cwd        = %CD% >> "%LOG%"
echo [env] arch       = %PROCESSOR_ARCHITECTURE% >> "%LOG%"
echo [env] comspec    = %COMSPEC% >> "%LOG%"

echo. >> "%LOG%"
echo [find] where python >> "%LOG%"
where python >> "%LOG%" 2>&1
echo [find] where py >> "%LOG%"
where py >> "%LOG%" 2>&1

set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY where py >nul 2>nul && set "PY=py -3"
echo [find] selected PY = [%PY%] >> "%LOG%"

if not defined PY goto nopython

echo [run] %PY% --version >> "%LOG%"
%PY% --version >> "%LOG%" 2>&1

echo [run] %PY% tools\setup_env.py >> "%LOG%"
%PY% "%~dp0tools\setup_env.py" >> "%LOG%" 2>&1
set "RC=%ERRORLEVEL%"
echo [run] exit code = %RC% >> "%LOG%"
goto show

:nopython
echo [!!] Python not found in PATH >> "%LOG%"
set "RC=1"

:show
type "%LOG%"
echo.
echo ============================================================
echo   Log saved to: %LOG%
echo ============================================================
echo.
pause
exit /b %RC%
