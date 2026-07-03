@echo off
setlocal

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

set "DIST=%ROOT%\dist"
set "BUILD=%ROOT%\build"
set "SPEC=%BUILD%\spec"
set "ICON=%ROOT%\packaging\assets\logo.ico"
set "RUNTIME_LOGO=%ROOT%\amazify\assets\logo.png"
set "AMAZIFY_ENTRY=%ROOT%\packaging\amazify_cli.py"
set "INNO_SCRIPT=%ROOT%\packaging\Amazify.iss"
set "ISCC=ISCC.exe"

if exist "%ROOT%\.venv\Scripts\python.exe" (
    set "PYTHON=%ROOT%\.venv\Scripts\python.exe"
) else (
    set "PYTHON=python"
)

pushd "%ROOT%" || exit /b 1

if exist "%BUILD%" rmdir /s /q "%BUILD%"
if not exist "%DIST%" mkdir "%DIST%"
if not exist "%SPEC%" mkdir "%SPEC%"
if exist "%DIST%\amazify.exe" del /f /q "%DIST%\amazify.exe"
if exist "%DIST%\amazifyw.exe" del /f /q "%DIST%\amazifyw.exe"
if exist "%DIST%\AmazifySetup.exe" del /f /q "%DIST%\AmazifySetup.exe"

if not exist "%ICON%" (
    echo Expected icon missing: %ICON%
    popd
    exit /b 1
)
if not exist "%RUNTIME_LOGO%" (
    echo Expected runtime logo missing: %RUNTIME_LOGO%
    popd
    exit /b 1
)

call :run "%PYTHON%" -m PyInstaller --noconfirm --clean --onefile --console --icon "%ICON%" --add-data "%RUNTIME_LOGO%;amazify\assets" --name amazify --distpath "%DIST%" --workpath "%BUILD%\amazify" --specpath "%SPEC%" "%AMAZIFY_ENTRY%"
if errorlevel 1 goto :fail

set "AMAZIFY_EXE=%DIST%\amazify.exe"
if not exist "%AMAZIFY_EXE%" (
    echo Expected build output missing: %AMAZIFY_EXE%
    goto :fail
)

call :run "%PYTHON%" -m PyInstaller --noconfirm --clean --onefile --windowed --icon "%ICON%" --add-data "%RUNTIME_LOGO%;amazify\assets" --name amazifyw --distpath "%DIST%" --workpath "%BUILD%\amazifyw" --specpath "%SPEC%" "%AMAZIFY_ENTRY%"
if errorlevel 1 goto :fail

set "AMAZIFYW_EXE=%DIST%\amazifyw.exe"
if not exist "%AMAZIFYW_EXE%" (
    echo Expected build output missing: %AMAZIFYW_EXE%
    goto :fail
)

where "%ISCC%" >nul 2>nul
if errorlevel 1 (
    if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" (
        set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
    ) else if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" (
        set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
    ) else (
        echo Inno Setup 6 compiler not found. Install Inno Setup 6 or add ISCC.exe to PATH.
        echo Built:
        echo - %AMAZIFY_EXE%
        echo - %AMAZIFYW_EXE%
        popd
        exit /b 1
    )
)

call :run "%ISCC%" "%INNO_SCRIPT%"
if errorlevel 1 goto :fail

set "SETUP_EXE=%DIST%\AmazifySetup.exe"
if not exist "%SETUP_EXE%" (
    echo Expected installer output missing: %SETUP_EXE%
    goto :fail
)

echo(
echo Built:
echo - %AMAZIFY_EXE%
echo - %AMAZIFYW_EXE%
echo - %SETUP_EXE%
popd
exit /b 0

:run
echo + %*
call %*
exit /b %errorlevel%

:fail
popd
exit /b 1
