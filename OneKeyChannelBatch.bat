@echo off
cd /D "%~dp0"

call conda activate videolingo
if errorlevel 1 (
  echo Failed to activate conda environment: videolingo
  pause
  exit /b 1
)

call python -m batch.utils.channel_auto_pipeline --config batch/channel_auto.yaml

:end
pause
