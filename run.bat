@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 听漏者 · 压缩空气泄漏诊断智能体

where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo  [错误] 没找到 python 命令。
  echo  请先安装 Python 3.10+：https://www.python.org/downloads/
  echo  安装时务必勾选 "Add Python to PATH"
  echo.
  pause
  exit /b 1
)

if "%PORT%"=="" set PORT=8000
echo.
echo  正在启动，浏览器会自动打开 http://127.0.0.1:%PORT%
echo  关闭本窗口即停止服务。
echo.
start "" http://127.0.0.1:%PORT%
python app.py
pause
