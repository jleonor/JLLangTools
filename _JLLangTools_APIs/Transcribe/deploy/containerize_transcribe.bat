@echo off
setlocal enabledelayedexpansion

REM ──────────────────────────────────────────────────────────────────────────────
REM 1) Determine where appsettings.json is
REM ──────────────────────────────────────────────────────────────────────────────

REM %~dp0 is the directory this script lives in (with trailing slash)
set "SCRIPT_DIR=%~dp0"

REM If appsettings.json exists three levels up, use that; otherwise assume it’s here
if exist "%SCRIPT_DIR%..\..\..\appsettings.json" (
    for %%I in ("%SCRIPT_DIR%..\..\..\appsettings.json") do set "SETTINGS_FILE=%%~fI"
) else if exist "%SCRIPT_DIR%appsettings.json" (
    for %%I in ("%SCRIPT_DIR%appsettings.json")     do set "SETTINGS_FILE=%%~fI"
) else (
    echo ERROR: Could not find appsettings.json in %SCRIPT_DIR% or three levels up.
    pause
    exit /b 1
)

echo Using settings file: %SETTINGS_FILE%

REM ──────────────────────────────────────────────────────────────────────────────
REM 2) Read docker_port from JSON
REM ──────────────────────────────────────────────────────────────────────────────

for /f "usebackq delims=" %%A in (`
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
      "& { (Get-Content '%SETTINGS_FILE%' | ConvertFrom-Json).transcribe.docker_port }"
`) do set "DOCKER_PORT=%%A"

echo DOCKER_PORT = %DOCKER_PORT%

REM ──────────────────────────────────────────────────────────────────────────────
REM 3) Compute your Transcribe source folder in Windows and convert to WSL path
REM ──────────────────────────────────────────────────────────────────────────────

REM Derive project root by stripping "\appsettings.json" from SETTINGS_FILE
for %%I in ("%SETTINGS_FILE%") do set "PROJECT_ROOT=%%~dpI"

REM The Windows path to your Transcribe API code
set "WIN_SRC=%PROJECT_ROOT%_JLLangTools_APIs\Transcribe\"

REM Use wslpath to get a Linux‐style path for rsync
for /f "usebackq delims=" %%P in (`
    wsl wslpath -a -u "%WIN_SRC%"
`) do set "WSL_SRC=%%P"

echo WSL source folder = %WSL_SRC%

REM ──────────────────────────────────────────────────────────────────────────────
REM 4) Build & run in WSL
REM ──────────────────────────────────────────────────────────────────────────────

REM ensure target exists
wsl -e bash -c "mkdir -p ~/JLLangTools/_JLLangTools_APIs/Transcribe"

REM sync code
wsl -e bash -c "rsync -avu --exclude=venv --exclude=deploy %WSL_SRC% ~/JLLangTools/_JLLangTools_APIs/Transcribe"

REM build the Docker image
wsl -e bash -c "cd ~/JLLangTools/_JLLangTools_APIs/Transcribe && docker build -t transcribe-api ."

REM run it
wsl -e bash -c "docker run --gpus all --name transcribe-api -p %DOCKER_PORT%:%DOCKER_PORT% transcribe-api"

REM stop the container when done
wsl -e bash -c "docker stop transcribe-api"

pause
