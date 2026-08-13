@echo off
REM Launcher de um clique: prepara tudo e abre o painel no navegador.
REM Sempre roda a partir da pasta onde este .bat esta, nao importa de
REM onde foi chamado (evita erro de "arquivo nao encontrado").
setlocal
cd /d "%~dp0"

REM Cria o ambiente virtual so na primeira vez (se a pasta .venv ja
REM existe, pula direto pra ativacao — muito mais rapido nas proximas).
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

REM Ativa o venv nesta janela: a partir daqui, "python" e "pip" apontam
REM pro Python de dentro de .venv, nao pro Python global do Windows.
call .venv\Scripts\activate.bat

REM pip so baixa o que ainda nao esta instalado, entao rodar toda vez e
REM seguro e rapido (nao reinstala nada se ja estiver tudo la).
echo Verificando dependencias (so demora na primeira vez)...
pip install -q -r requirements.txt
if errorlevel 1 (
  echo.
  echo Falha ao instalar as dependencias. Veja o erro acima.
  pause
  exit /b 1
)

REM webui.py sobe o servidor local e abre o navegador sozinho. Essa
REM janela do .bat precisa continuar aberta enquanto o painel estiver
REM em uso (e o processo do servidor).
echo.
echo Abrindo o painel no navegador...
python webui.py

pause
