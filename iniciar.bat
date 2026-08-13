@echo off
setlocal
cd /d "%~dp0"

if not exist .venv (
  echo Criando ambiente virtual Python...
  python -m venv .venv
  if errorlevel 1 (
    echo.
    echo Nao foi possivel criar o ambiente virtual. Verifique se o Python esta instalado e no PATH.
    pause
    exit /b 1
  )
)

call .venv\Scripts\activate.bat

echo Verificando dependencias (so demora na primeira vez)...
pip install -q -r requirements.txt
if errorlevel 1 (
  echo.
  echo Falha ao instalar as dependencias. Veja o erro acima.
  pause
  exit /b 1
)

echo.
echo Abrindo o painel no navegador...
python webui.py

pause
