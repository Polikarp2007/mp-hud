@echo off
echo Cleaning build artifacts...

REM PyInstaller build/dist in project
if exist "%~dp0build" rmdir /s /q "%~dp0build"
if exist "%~dp0dist"  rmdir /s /q "%~dp0dist"

REM Build cache on D: (from --workpath builds)
if exist "D:\PoliCo_HUD_build" rmdir /s /q "D:\PoliCo_HUD_build"

REM __pycache__ in project
for /d /r "%~dp0" %%d in (__pycache__) do (
    if exist "%%d" rmdir /s /q "%%d"
)

REM Windows Temp (PyInstaller extraction leftovers, _MEI* folders)
for /d %%d in ("%TEMP%\_MEI*") do rmdir /s /q "%%d" 2>nul
for /d %%d in ("%LOCALAPPDATA%\Temp\_MEI*") do rmdir /s /q "%%d" 2>nul

echo Done. Space freed!
pause
