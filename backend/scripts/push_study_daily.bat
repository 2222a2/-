@echo off
setlocal

REM ---- 从本地密钥文件加载敏感变量（.secrets.bat 已被 .gitignore 排除，不进仓库）----
if exist "%~dp0.secrets.bat" (
  call "%~dp0.secrets.bat"
) else (
  echo [WARN] 未找到 %~dp0.secrets.bat，SERVERCHAN_KEY / STUDY_PAGE_TOKEN 缺失，推送与写库将失败。
  echo [WARN] 请复制 .secrets.bat.example 为同目录 .secrets.bat 并填入你的 key。
)

REM ============================================================
REM  备考任务·每日 23:00 自动推送（由 Windows 任务计划程序调用）
REM  作用：生成明天任务写入平台，并发微信推送（科目摘要+链接）。
REM  依赖：backend\.venv2 或 .venv 里的 Python。
REM ============================================================

REM ---- 备考页口令 STUDY_PAGE_TOKEN：已从 .secrets.bat 本地加载（勿在此硬编码）----

REM ---- 后端 API 地址（写库用，默认 8000）----
set STUDY_API_BASE=http://127.0.0.1:8000/api

REM ---- 微信点开链接的基地址（同 WiFi 用局域网IP，外出用 cloudflared 公网地址）----
set STUDY_WEB_BASE_URL=http://127.0.0.1:5173

REM ---- 推送通道：ServerChan key 已从 .secrets.bat 本地加载（勿在此硬编码）----

REM ---- 选 Python 虚拟环境：优先 .venv2，回退 .venv，再回退系统 python ----
set ROOT=%~dp0..
if exist "%ROOT%\.venv2\Scripts\python.exe" (
  set VENV=%ROOT%\.venv2\Scripts\python.exe
) else if exist "%ROOT%\.venv\Scripts\python.exe" (
  set VENV=%ROOT%\.venv\Scripts\python.exe
) else (
  set VENV=python
)

echo [%date% %time%] 开始生成明日备考任务...
"%VENV%" "%ROOT%\scripts\gen_study_tasks.py"
echo [%date% %time%] 完成（退出码 %errorlevel%）。若未收到微信，请检查 SERVERCHAN_KEY 与后端是否在线。
endlocal
