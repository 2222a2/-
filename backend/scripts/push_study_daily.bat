@echo off
setlocal
REM ============================================================
REM  备考任务·每日 23:00 自动推送（由 Windows 任务计划程序调用）
REM  作用：生成明天任务写入平台，并发微信推送（科目摘要+链接）。
REM  依赖：backend\.venv2 或 .venv 里的 Python。
REM ============================================================

REM ---- 必填：备考页口令（与 start_study.bat / 后端 STUDY_PAGE_TOKEN 保持一致）----
set STUDY_PAGE_TOKEN=guoguo2026

REM ---- 后端 API 地址（写库用，默认 8000）----
set STUDY_API_BASE=http://127.0.0.1:8000/api

REM ---- 微信点开链接的基地址（同 WiFi 用局域网IP，外出用 cloudflared 公网地址）----
set STUDY_WEB_BASE_URL=http://127.0.0.1:5173

REM ---- 推送通道（四选一，此处用方糖 ServerChan，推到个人微信）----
REM  ↓↓↓ 方糖 ServerChan key：请填入【你自己的】ServerChan token（旧 key 已泄露，请去 sct.ftqq.com 后台轮换）↓↓↓
set SERVERCHAN_KEY=your_serverchan_key_here

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
