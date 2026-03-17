@echo off
pyinstaller ^
  --onefile ^
  --noconsole ^
  --name "Aeyori" ^
  --icon=icon.ico ^
  --exclude-module easyocr ^
  --exclude-module torch ^
  --exclude-module torchvision ^
  --exclude-module cv2 ^
  --exclude-module numpy ^
  launcher.py
echo.
echo Build complete. Check dist\Aeyori.exe
pause
