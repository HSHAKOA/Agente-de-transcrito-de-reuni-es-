@echo off
REM Launcher de um clique: prepara tudo e abre o painel no navegador.
REM Sempre roda a partir da pasta onde este .bat esta, nao importa de
REM onde foi chamado (evita erro de "arquivo nao encontrado").
setlocal
cd /d "%~dp0"

REM --- Python -----------------------------------------------------------
REM Checa ANTES de tentar usar: a mensagem do Windows quando "python" nao
REM existe ("nao e reconhecido como um comando interno") nao diz o que
REM fazer, e em algumas instalacoes abre a Microsoft Store sozinha.
where python >nul 2>&1
if errorlevel 1 (
  echo.
  echo [ERRO] O Python nao foi encontrado no PATH.
  echo.
  echo   Instale o Python 3.9 ou mais novo em https://www.python.org/downloads/
  echo   e marque "Add Python to PATH" durante a instalacao.
  echo.
  pause
  exit /b 1
)

REM --- Ambiente virtual -------------------------------------------------
REM Criado so na primeira vez. O painel PRECISA rodar dentro dele: com o
REM Python global (sem soundcard/tzdata) o painel sobe normalmente e so
REM falha quando uma gravacao agendada tenta comecar -- aconteceu em
REM 21/09/2026 e uma aula inteira nao gravou.
if not exist .venv (
  echo Criando ambiente virtual Python...
  python -m venv .venv
  if errorlevel 1 (
    echo.
    echo [ERRO] Nao foi possivel criar o ambiente virtual .venv.
    echo   Veja a mensagem acima. Em geral e falta de permissao na pasta
    echo   ou uma instalacao do Python sem o modulo venv.
    echo.
    pause
    exit /b 1
  )
)

if not exist .venv\Scripts\activate.bat (
  echo.
  echo [ERRO] A pasta .venv existe mas esta incompleta (sem Scripts\activate.bat^).
  echo   Apague a pasta .venv e rode este arquivo de novo.
  echo.
  pause
  exit /b 1
)

REM Ativa o venv nesta janela: a partir daqui, "python" e "pip" apontam
REM pro Python de dentro de .venv, nao pro Python global do Windows.
call .venv\Scripts\activate.bat

REM --- Dependencias -----------------------------------------------------
REM pip so baixa o que ainda nao esta instalado, entao rodar toda vez e
REM seguro e rapido (nao reinstala nada se ja estiver tudo la).
echo Verificando dependencias (so demora na primeira vez)...
pip install -q -r requirements.txt
if errorlevel 1 (
  echo.
  echo [ERRO] Falha ao instalar as dependencias. Veja o erro acima.
  echo   Sem internet na primeira execucao, este passo nao tem como terminar.
  echo.
  pause
  exit /b 1
)

REM --- Build do React ---------------------------------------------------
REM Um clone limpo nao tem frontend\dist (nao e versionado, ver .gitignore).
REM Sem ele o painel serve a interface LEGADA automaticamente -- funciona,
REM mas nao e o produto. Avisar aqui evita a conclusao errada de que o
REM projeto "e feio" ou de que o React esta quebrado.
if not exist frontend\dist\index.html (
  echo.
  echo [AVISO] O build do React ainda nao existe (frontend\dist^).
  echo   O painel vai abrir na interface LEGADA, que e um fallback.
  echo.
  where npm >nul 2>&1
  if errorlevel 1 (
    echo   Para gerar a interface atual, instale o Node.js 20+ em
    echo   https://nodejs.org/ e depois rode:
  ) else (
    echo   O Node.js ja esta instalado aqui. Para gerar a interface atual, rode:
  )
  echo.
  echo       cd frontend
  echo       npm install
  echo       npm run build
  echo.
)

REM webui.py sobe o servidor local e abre o navegador sozinho. Essa
REM janela do .bat precisa continuar aberta enquanto o painel estiver
REM em uso (e o processo do servidor). Ele ainda faz a propria checagem
REM de ambiente e imprime [ATENCAO] para o que estiver faltando.
echo.
echo Abrindo o painel no navegador...
python webui.py

pause
