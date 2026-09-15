@echo off
setlocal EnableExtensions DisableDelayedExpansion
set "_S2V_PYTHON="
set "_S2V_PYTHONW="

cd /d "%~dp0"
if errorlevel 1 goto :project_not_found

if defined SERUM2VITAL_PYTHON (
    set "_S2V_PYTHON=%SERUM2VITAL_PYTHON:"=%"
    goto :use_python_executable
)

if exist ".venv\Scripts\python.exe" (
    set "_S2V_PYTHON=%CD%\.venv\Scripts\python.exe"
    goto :use_python_executable
)

where py.exe >nul 2>nul
if not errorlevel 1 goto :use_python_launcher

:find_path_python
for /f "delims=" %%P in ('where python.exe 2^>nul') do (
    if not defined _S2V_PYTHON (
        "%%P" -c "import sys; raise SystemExit(sys.version_info < (3, 9))" >nul 2>nul
        if not errorlevel 1 set "_S2V_PYTHON=%%P"
    )
)
if defined _S2V_PYTHON goto :use_python_executable
goto :python_not_found

:use_python_launcher
py.exe -3 -c "import sys; raise SystemExit(sys.version_info < (3, 9))" >nul 2>nul
if errorlevel 1 goto :find_path_python

py.exe -3 -c "import PySide6, serum2vital.gui" >nul 2>nul
if errorlevel 1 goto :gui_not_installed_launcher

where pyw.exe >nul 2>nul
if errorlevel 1 (
    "%ComSpec%" /d /c exit 0
    start "" py.exe -3 -m serum2vital.gui
) else (
    "%ComSpec%" /d /c exit 0
    start "" pyw.exe -3 -m serum2vital.gui
)
if errorlevel 1 goto :launch_failed
exit /b 0

:use_python_executable
"%_S2V_PYTHON%" -c "import sys; raise SystemExit(sys.version_info < (3, 9))" >nul 2>nul
if errorlevel 1 goto :python_unusable

"%_S2V_PYTHON%" -c "import PySide6, serum2vital.gui" >nul 2>nul
if errorlevel 1 goto :gui_not_installed_executable

for %%P in ("%_S2V_PYTHON%") do set "_S2V_PYTHONW=%%~dpPpythonw.exe"
if exist "%_S2V_PYTHONW%" (
    "%ComSpec%" /d /c exit 0
    start "" "%_S2V_PYTHONW%" -m serum2vital.gui
) else (
    "%ComSpec%" /d /c exit 0
    start "" "%_S2V_PYTHON%" -m serum2vital.gui
)
if errorlevel 1 goto :launch_failed
exit /b 0

:gui_not_installed_launcher
echo.
echo Serum2Vital GUI could not be started with the detected Python.
echo Install the GUI dependencies from this folder, then try again:
echo.
echo     py -3 -m pip install -e ".[gui,serum2]"
goto :gui_install_footer

:gui_not_installed_executable
echo.
echo Serum2Vital GUI could not be started with the detected Python.
echo Install the GUI dependencies from this folder, then try again:
echo.
echo     "%_S2V_PYTHON%" -m pip install -e ".[gui,serum2]"

:gui_install_footer
echo.
pause
exit /b 1

:python_not_found
echo.
echo Python 3 was not found. Install Python 3.9 or newer and try again.
echo https://www.python.org/downloads/windows/
echo.
pause
exit /b 1

:python_unusable
echo.
echo The selected Python could not run or is older than Python 3.9:
echo     "%_S2V_PYTHON%"
echo.
pause
exit /b 1

:project_not_found
echo.
echo The Serum2Vital project folder could not be opened.
echo.
pause
exit /b 1

:launch_failed
echo.
echo Windows could not launch the Serum2Vital GUI process.
echo.
pause
exit /b 1
