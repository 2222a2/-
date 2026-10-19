#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
常驻调度器：绕过 Windows 任务计划程序 / 管理员权限限制。
不需要管理员，普通用户即可运行；每天 23:00 自动触发备考任务生成 + 微信推送。
失去的代价：任务计划程序的「唤醒计算机」能力没了 —— 电脑睡眠时不会触发，
但开机/唤醒后会立即补跑一次（见下方 last_run 去重逻辑）。
"""
import os
import sys
import time
import datetime
import subprocess

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BAT_PATH = os.path.join(SCRIPT_DIR, "push_study_daily.bat")
# 记录"今天是否已跑过"，避免唤醒/重启后重复推送
FLAG_FILE = os.path.join(SCRIPT_DIR, "..", "data", "last_push_date.txt")

# 触发时间（小时:分钟）
TRIGGER_HOUR = 23
TRIGGER_MINUTE = 0


def already_ran_today():
    try:
        if not os.path.exists(FLAG_FILE):
            return False
        with open(FLAG_FILE, "r", encoding="utf-8") as f:
            d = f.read().strip()
        return d == datetime.date.today().isoformat()
    except Exception:
        return False


def mark_ran_today():
    try:
        os.makedirs(os.path.dirname(FLAG_FILE), exist_ok=True)
        with open(FLAG_FILE, "w", encoding="utf-8") as f:
            f.write(datetime.date.today().isoformat())
    except Exception as e:
        print(f"[warn] 写去重标记失败: {e}")


def trigger():
    """到点触发：调用 push_study_daily.bat（其内部已配好所有环境变量）。"""
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if already_ran_today():
        print(f"[{now}] 今天已推送过，跳过")
        return
    print(f"[{now}] 触发备考推送 -> {BAT_PATH}")
    try:
        # Windows 下直接跑 .bat；用 shell=True 确保 cmd 接管
        subprocess.run(BAT_PATH, shell=True, capture_output=True, text=True, timeout=300)
        mark_ran_today()
        print(f"[{now}] 推送完成")
    except subprocess.TimeoutExpired:
        print(f"[{now}] 推送超时（>300s）")
    except Exception as e:
        print(f"[{now}] 推送异常: {e}")


def seconds_to_next_trigger():
    now = datetime.datetime.now()
    target = now.replace(hour=TRIGGER_HOUR, minute=TRIGGER_MINUTE, second=0, microsecond=0)
    if now >= target:
        target += datetime.timedelta(days=1)
    return (target - now).total_seconds()


def main():
    print(f"[启动] 备考推送常驻调度器（每天 {TRIGGER_HOUR:02d}:{TRIGGER_MINUTE:02d} 触发）")
    print(f"[启动] 脚本目录: {SCRIPT_DIR}")
    # 若启动时已过 23:00 且今天没跑过 -> 立即补跑一次（应对睡眠/未开机）
    now = datetime.datetime.now()
    if now.hour >= TRIGGER_HOUR and now.minute >= TRIGGER_MINUTE and not already_ran_today():
        trigger()
    while True:
        secs = seconds_to_next_trigger()
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 距下次触发 {secs/3600:.2f} 小时")
        time.sleep(secs)
        trigger()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[退出] 调度器已停止")
        sys.exit(0)
