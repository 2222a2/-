@echo off
REM 用 pythonw 后台无窗口启动常驻调度器（不需要管理员）
REM 作用：每天 23:00 自动生成备考任务并推送微信，绕开任务计划程序/管理员限制
setlocal
set "PYW=C:\Users\用户\worklearn-platform\backend\.venv2\Scripts\pythonw.exe"
set "SCH=C:\Users\用户\worklearn-platform\backend\scripts\scheduler_daily.py"
if not exist "%PYW%" (
  echo [错误] 找不到 pythonw：%PYW%
  echo 请确认 backend\.venv2 虚拟环境存在。
  pause
  exit /b 1
)
start "" "%PYW%" "%SCH%"
echo [已启动] 备考推送调度器已后台运行（无窗口）。
echo  - 每天 23:00 自动推送；电脑睡眠不会触发，开机/唤醒后补跑。
echo  - 停止方法：任务管理器结束 pythonw.exe 进程。
echo  - 开机自启：把本 bat 的快捷方式放进「启动」文件夹（Win+R 输入 shell:startup）。
endlocal
