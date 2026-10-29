@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === Amazon.fr Firsat Avcisi - kurulum ===

where python >nul 2>nul
if errorlevel 1 (
  echo Python bulunamadi. Once Python 3.10+ kurun:
  echo   winget install Python.Python.3.12 --scope user
  echo veya https://www.python.org/downloads/ ^(kurarken "Add python.exe to PATH" isaretleyin^)
  echo Sonra bu pencereyi kapatip kurulum.bat'i tekrar calistirin.
  pause
  exit /b 1
)
python --version

if not exist .env (
  copy .env.example .env >nul
  echo .env dosyasi olusturuldu. Not Defteri ile acip Telegram bilgilerinizi yazin.
)

echo.
echo Testler calistiriliyor...
python -m unittest discover -s tests -t . -v
if errorlevel 1 (
  echo BAZI TESTLER BASARISIZ. Yukaridaki ciktiyi kontrol edin.
) else (
  echo Tum testler gecti.
)
echo.
echo Kurulum tamam. Baslatmak icin: baslat.bat
pause
