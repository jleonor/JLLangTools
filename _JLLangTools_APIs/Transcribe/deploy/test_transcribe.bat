@echo off
setlocal EnableDelayedExpansion

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

:: Retrieve API URL from JSON settings
for /f "delims=" %%A in ('powershell -NoProfile -Command "(Get-Content '%SETTINGS_FILE%' | ConvertFrom-Json).transcribe.api_url"') do set API_URL=%%A
echo API URL is %API_URL%

:: --- NEW: Check device endpoint ---
for /f "delims=" %%D in (
    'powershell -NoProfile -Command "(Invoke-RestMethod '%API_URL%/device').device"'
) do set DEVICE=%%D
echo Device in use: %DEVICE%
echo.

:: --- NEW: Get supported languages ---
echo Fetching supported languages from API...
powershell -NoProfile -Command "(Invoke-RestMethod '%API_URL%/languages').languages -join ', '"
echo.

:: Define the test files directory
set TEST_FILES_DIR=%~dp0test_files

:: Loop through all mp3 files in the test_files directory
for %%F in ("%TEST_FILES_DIR%\*.mp3") do (
    set "AUDIO_FILE=%%F"
    
    :: Extract the language key from the filename
    set "FILE_NAME=%%~nF"
    
    :: Assign language key based on filename
    if "!FILE_NAME!"=="en-test" set "LANG_KEY=en"
    if "!FILE_NAME!"=="fr-test" set "LANG_KEY=fr"
    if "!FILE_NAME!"=="es-test" set "LANG_KEY=es"
    if "!FILE_NAME!"=="xx-large-test" set "LANG_KEY=xx-large"
    if "!FILE_NAME!"=="xx-medium-test" set "LANG_KEY=xx-medium"

    :: Ensure variables are correctly set
    echo Processing file: !AUDIO_FILE!
    echo Language Key: !LANG_KEY!
    
    :: Ensure backslashes in file paths (for Windows compatibility)
    set "AUDIO_FILE=!AUDIO_FILE:/=\!"

    :: Send the file to the API
    echo Sending audio file to API...
    curl -X POST -F "audio=@!AUDIO_FILE!" -F "lang_key=!LANG_KEY!" !API_URL!/transcribe
    echo.
)

pause
