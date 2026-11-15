@echo off
setlocal
cd /d "%~dp0"
echo ==============================
echo  MeetWithMe AI - Setup
echo ==============================
echo.

where py >nul 2>nul
if errorlevel 1 goto nopython

py -3.11 --version >nul 2>nul
if errorlevel 1 goto nopython

if not exist .venv\Scripts\python.exe (
    echo Creating virtual environment...
    py -3.11 -m venv .venv
    if errorlevel 1 goto failed
)

call .venv\Scripts\activate.bat

echo Installing packages (this can take a few minutes the first time)...
python -m pip install --upgrade pip
python -m pip install -r requirements-live.txt
if errorlevel 1 goto failed

if not exist .env (
    > .env echo GEMINI_API_KEY=
    echo.
    echo A .env file was created. In the file that opens, type your own
    echo Gemini API key after GEMINI_API_KEY= and save it.
    notepad .env
)

echo.
echo Setup complete. Run start.bat to start the program.
pause
exit /b 0

:nopython
echo Python 3.11 was not found.
echo Install Python 3.11 from https://www.python.org/downloads/
echo During setup, tick "Add python.exe to PATH",
echo then run this file again.
pause
exit /b 1

:failed
echo.
echo Setup failed. Please note the error message above.
pause
exit /b 1
