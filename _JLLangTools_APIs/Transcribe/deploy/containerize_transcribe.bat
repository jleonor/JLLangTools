@echo off
:: Define the path to the settings file
set SETTINGS_FILE=C:\Users\jonat\OneDrive\Desktop\DevProjects\JLLangTools\appsettings.json

:: Extract docker_port from JSON using PowerShell and capture the output
for /f "usebackq delims=" %%A in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "& { (Get-Content '%SETTINGS_FILE%' | ConvertFrom-Json).transcribe.docker_port }"`) do set DOCKER_PORT=%%A

:: Display the extracted value
echo DOCKER_PORT is %DOCKER_PORT%


wsl -e bash -c "mkdir -p ~/DevProjects/JLLangTools/_JLLangTools_APIs"
wsl -e bash -c "rsync -avu --exclude='venv' --exclude='deploy' /mnt/c/Users/jonat/OneDrive/Desktop/DevProjects/JLLangTools/_JLLangTools_APIs/Transcribe/ ~/DevProjects/JLLangTools/_JLLangTools_APIs/Transcribe"
wsl -e bash -c "cd ~/DevProjects/JLLangTools/_JLLangTools_APIs/Transcribe && docker build -t transcribe-api ."
wsl -e bash -c "docker run --gpus all --name transcribe-api -p %DOCKER_PORT%:%DOCKER_PORT% transcribe-api"

wsl -e bash -c "docker stop transcribe-api"

pause
