@echo off
pyinstaller ^
  --onefile ^
  --noconsole ^
  --name "Aeyori" ^
  --icon=icon.ico ^
  --collect-all easyocr ^
  --collect-all torch ^
  --collect-all torchvision ^
  launcher.py
echo.
echo Build complete. Check dist\Aeyori.exe
pause
