@echo off
pushd "%~dp0.."
pyinstaller --clean --noconfirm KarutaBot\Aeyori.spec
set "BUILD_EXIT_CODE=%ERRORLEVEL%"
popd
echo.
if %BUILD_EXIT_CODE% equ 0 (
  echo Build complete. Check dist\Aeyori.exe
) else (
  echo Build failed with exit code %BUILD_EXIT_CODE%.
)
pause
exit /b %BUILD_EXIT_CODE%
