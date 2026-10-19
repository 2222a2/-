@echo off
chcp 65001 >nul
setlocal
REM ============================================================
REM  备考任务 一键启动（方案B：同 WiFi 局域网，手机可改）
REM  用法：把本文件放在 worklearn-platform 根目录，双击即可。
REM  前提：后端依赖装在 backend\.venv2 或 .venv 里。
REM ============================================================
set STUDY_PAGE_TOKEN=guoguo2026
set ROOT=%~dp0

REM 选 Python 虚拟环境：优先 .venv2，回退 .venv，再回退系统 python
if exist "%ROOT%backend\.venv2\Scripts\python.exe" (
  set VENV=%ROOT%backend\.venv2\Scripts\python.exe
) else if exist "%ROOT%backend\.venv\Scripts\python.exe" (
  set VENV=%ROOT%backend\.venv\Scripts\python.exe
) else (
  set VENV=python
)

echo 正在启动后端(8000)与前端(5173)，会各开一个窗口...
start "worklearn-backend" cmd /k "cd /d %ROOT%backend && set STUDY_PAGE_TOKEN=%STUDY_PAGE_TOKEN% && %VENV% -m uvicorn app.main:app --port 8000"
start "worklearn-frontend" cmd /k "cd /d %ROOT%frontend && npm run dev"

echo.
echo ============================================================
echo  启动完成后：手机连与电脑【同一个 WiFi】，浏览器打开：
echo    http://[电脑局域网IP]:5173/study-tasks
echo  查电脑局域网IP：另开一个 cmd，输入  ipconfig
echo    找 “无线局域网适配器 WLAN” 或 “Wi-Fi” 下的 IPv4 地址
echo  首次打开页面输入口令：%STUDY_PAGE_TOKEN%
echo ------------------------------------------------------------
echo  方糖推送时，把生成器的环境变量设为：
echo    STUDY_WEB_BASE_URL=http://[电脑局域网IP]:5173
echo ============================================================
pause
