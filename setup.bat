@echo off
setlocal
cd /d "%~dp0"
echo ==============================
echo  MeetWithMe AI - Setup
echo ==============================
echo.

set "PYCMD="

py -3.11 --version >nul 2>nul
if not errorlevel 1 set "PYCMD=py -3.11"

if not defined PYCMD (
    py -3 --version >nul 2>nul
    if not errorlevel 1 set "PYCMD=py -3"
)

if not defined PYCMD (
    python --version >nul 2>nul
    if not errorlevel 1 set "PYCMD=python"
)

if not defined PYCMD goto nopython

echo Using:
%PYCMD% --version

%PYCMD% -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)"
if errorlevel 1 goto oldpython

if not exist .venv\Scripts\python.exe (
    echo Creating virtual environment...
    %PYCMD% -m venv .venv
    if errorlevel 1 goto failed
)

echo Installing packages. The first time this can take a few minutes...
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto failed

if not exist .env (
    > .env echo GEMINI_API_KEY=
    echo.
    echo A .env file was created. In the file that opens, type your own
    echo Gemini API key after GEMINI_API_KEY= and save the file.
    notepad .env
)

echo.
echo Setup complete. Run start.bat to start the program.
pause
exit /b 0

:nopython
echo No working Python was found.
echo Tried: py -3.11, py -3 and python.
echo Install Python 3.11 from https://www.python.org/downloads/
echo During setup, tick "Add python.exe to PATH", then run this file again.
echo If Python came from the Microsoft Store, install it from python.org instead.
pause
exit /b 1

:oldpython
echo This Python is too old. Python 3.9 or newer is required, 3.11 is recommended.
pause
exit /b 1

:failed
echo.
echo Setup failed. Please copy the error message above and send it to the author.
pause
exit /b 1
