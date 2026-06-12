@echo off
chcp 65001 >nul
title Consulta de Comissao - Farmácias Estrela
cd /d "%~dp0"

set URL=http://localhost:8000

echo.
echo [Consulta de Comissao] Iniciando aplicacao...
echo.

if exist "venv\Scripts\python.exe" (
    start "Servidor - Consulta Comissao" /d "%~dp0" venv\Scripts\python.exe app.py
) else (
    start "Servidor - Consulta Comissao" /d "%~dp0" python app.py
)

echo Aguardando o servidor iniciar...
timeout /t 3 /nobreak >nul

start "" "%URL%"

echo Navegador aberto. A janela do servidor permanece aberta; feche-a para encerrar o app.
echo.
pause
