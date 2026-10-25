@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 听漏者 · 在线模式启动

echo ============================================================
echo   听漏者 · 在线模式启动器
echo ============================================================
echo.
echo   下面会问你三个值。右键就能粘贴，粘完按回车。
echo   如果某项不知道，直接按回车跳过（那样会退回规则模式，也能用）。
echo.
set "LLM_BASE_URL="
set "LLM_API_KEY="
set "LLM_MODEL="

set /p LLM_BASE_URL=  1) 接口地址（一般以 /v1 结尾）: 
set /p LLM_API_KEY=  2) API Key: 
set /p LLM_MODEL=  3) 模型名: 
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo  [错误] 没找到 python。请先安装 Python 3.10+ 并勾选 Add Python to PATH
  echo.
  pause
  exit /b 1
)

echo  正在体检……
echo.
python doctor.py
echo.
echo ------------------------------------------------------------
echo  体检完按任意键启动网页（规则模式下也能正常演示）
echo ------------------------------------------------------------
pause >nul

if "%PORT%"=="" set "PORT=8000"
start "" http://127.0.0.1:%PORT%
python app.py
pause
