@echo off
set "APP_DIR=C:\Users\f3011542\Documents\GitHub\NewDjeFinder"
set "APP_FILE=%APP_DIR%\app.py"
set "STREAMLIT_FILE=%APP_DIR%\streamlit_app.py"

if not exist "%APP_FILE%" (
    echo Nao encontrei o app em:
    echo %APP_FILE%
    pause
    exit /b 1
)

if not exist "%STREAMLIT_FILE%" (
    echo Nao encontrei o Streamlit em:
    echo %STREAMLIT_FILE%
    pause
    exit /b 1
)

cd /d "%APP_DIR%"
start "DJE Finder Streamlit" /min cmd /c python -m streamlit run "%STREAMLIT_FILE%"
python "%APP_FILE%"
