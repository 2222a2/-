"""M6 复盘视频合成：matplotlib 逐帧渲染 + moviepy 合成 mp4。

依赖 matplotlib / moviepy（需装在后端 venv，见《Phase2 实施方案》§1 / §3.4）。
所有重依赖都在函数内部 lazy import，保证本模块即使缺依赖也能被 import（reward.py 照常挂载）。

视频内容（5 帧，每帧 2.5s）：
  1) 封面：标题 + 积分/等级/连续打卡 + 徽章进度
  2) 近 30 天日完成率走势
  3) 本周各科完成度
  4) 徽章墙（已得高亮 / 未得灰显）
  5) 结尾鼓励页
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

from .config import DATA_DIR
from . import db

VIDEO_DIR = DATA_DIR / "videos"

# 科目 code -> 中文名（视频里更友好）
SUBJECT_CN = {
    "math": "数学一",
    "english": "英语一",
    "cs408": "408",
    "ds": "数据结构",
    "other": "其他",
}


def _cjk_font() -> str | None:
    """挑一个系统里存在的 CJK 字体给 matplotlib，避免中文变方框；找不到返回 None。"""
    candidates = [
        "C:/Windows/Fonts/msyh.ttc",    # 微软雅黑
        "C:/Windows/Fonts/simhei.ttf",  # 黑体
        "C:/Windows/Fonts/simsun.ttc",  # 宋体
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/System/Library/Fonts/PingFang.ttc",
    ]
    for f in candidates:
        if os.path.exists(f):
            return f
    return None


def generate_review_video(period_label: str | None = None, days: int = 30) -> dict:
    """合成本期复盘视频，落库并返回视频记录（含 file_url）。

    Raises:
        RuntimeError: 缺 matplotlib / moviepy 依赖时给出可操作提示。
    """
    # ---- 重依赖 lazy import ----
    try:
        import matplotlib
        matplotlib.use("Agg")  # 无 GUI 后端
        import matplotlib.pyplot as plt
        from matplotlib import font_manager
        from matplotlib.patches import FancyBboxPatch
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "matplotlib 未安装：请在后端 venv 执行 `pip install matplotlib moviepy`"
        ) from e
    try:
        from moviepy import ImageClip, concatenate_videoclips
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "moviepy 未安装：请在后端 venv 执行 `pip install moviepy`"
        ) from e

    # ---- 中文字体 ----
    cn_font = _cjk_font()
    if cn_font:
        font_manager.fontManager.addfont(cn_font)
        name = font_manager.FontProperties(fname=cn_font).get_name()
        plt.rcParams["font.sans-serif"] = [name, "DejaVu Sans"]
        plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["axes.unicode_minus"] = False

    # ---- 取数据 ----
    state = db.get_reward_state()
    today = datetime.now()
    end = today.strftime("%Y-%m-%d")
    start = (today - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    cal = db.daily_completion_map(start, end)
    week_start = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")
    week_end = (today + timedelta(days=6 - today.weekday())).strftime("%Y-%m-%d")
    wp = db.weekly_progress(week_start, week_end)

    period_label = period_label or f"{today.strftime('%Y 年 %m 月')} 学习复盘"
    earned = [b for b in state["all_badges"] if b["earned"]]

    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    frame_dir = VIDEO_DIR / f"_frames_{today.strftime('%Y%m%d%H%M%S')}"
    frame_dir.mkdir(exist_ok=True)
    frames: list[str] = []

    def save(fig, name: str) -> None:
        p = frame_dir / name
        fig.savefig(p, dpi=120, facecolor="#0f1f33")
        plt.close(fig)
        frames.append(str(p))

    # 统一配色
    BG = "#0f1f33"
    ACCENT = "#4fa3ff"
    GOLD = "#ffd54f"
    MUTE = "#8aa6c8"

    # ---------- 帧 1：封面 ----------
    fig = plt.figure(figsize=(16, 9), facecolor=BG)
    fig.text(0.5, 0.70, period_label, ha="center", color="white",
             fontsize=48, fontweight="bold")
    fig.text(0.5, 0.54,
             f"积分 {state['points']}    ·    Lv.{state['level']}    ·    连续打卡 {state['streak']} 天",
             ha="center", color=ACCENT, fontsize=26)
    fig.text(0.5, 0.44,
             f"累计打卡 {state['checkin_total']} 次    ·    解锁徽章 {len(earned)}/{len(state['all_badges'])}",
             ha="center", color="#cfe6ff", fontsize=22)
    fig.text(0.5, 0.12, today.strftime("%Y-%m-%d"), ha="center",
             color=MUTE, fontsize=18)
    save(fig, "f1_cover.png")

    # ---------- 帧 2：近 days 天完成率走势 ----------
    fig = plt.figure(figsize=(16, 9), facecolor=BG)
    fig.text(0.5, 0.90, f"近 {days} 天每日完成率", ha="center",
             color="white", fontsize=30, fontweight="bold")
    ax = fig.add_axes([0.07, 0.12, 0.86, 0.68])
    xs = list(range(len(cal)))
    rates = [c["rate"] * 100 for c in cal]
    colors = [GOLD if r >= 80 else (ACCENT if r >= 40 else MUTE) for r in rates]
    ax.bar(xs, rates, color=colors, width=0.8)
    ax.set_ylim(0, 100)
    ax.set_facecolor(BG)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.spines["left"].set_color(MUTE)
    ax.spines["bottom"].set_color(MUTE)
    ax.tick_params(colors=MUTE, labelsize=12)
    ax.set_ylabel("完成率 %", color=MUTE, fontsize=14)
    # x 轴每隔几天标一个日期
    step = max(1, len(cal) // 10)
    ax.set_xticks(xs[::step])
    ax.set_xticklabels([cal[i]["date"][5:] for i in xs[::step]], rotation=0)
    fig.text(0.5, 0.05, f"平均完成率 {sum(rates) / len(rates):.0f}%",
             ha="center", color="#cfe6ff", fontsize=18)
    save(fig, "f2_trend.png")

    # ---------- 帧 3：本周各科完成 ----------
    fig = plt.figure(figsize=(16, 9), facecolor=BG)
    fig.text(0.5, 0.90, "本周各科完成", ha="center",
             color="white", fontsize=30, fontweight="bold")
    ax = fig.add_axes([0.12, 0.14, 0.76, 0.66])
    subs = wp["by_subject"] or {}
    labels = [SUBJECT_CN.get(k, k) for k in subs.keys()]
    dones = [v["done"] for v in subs.values()]
    totals = [v["total"] for v in subs.values()]
    y = list(range(len(labels)))[::-1]
    ax.barh(y, totals, color="#23344d", height=0.5, label="任务数")
    ax.barh(y, dones, color=ACCENT, height=0.5, label="已完成")
    ax.set_yticks(y)
    ax.set_yticklabels(labels, color="white", fontsize=16)
    ax.set_facecolor(BG)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.spines["left"].set_color(MUTE)
    ax.spines["bottom"].set_color(MUTE)
    ax.tick_params(colors=MUTE, labelsize=12)
    ax.legend(facecolor=BG, labelcolor=MUTE, loc="lower right")
    if subs:
        fig.text(0.5, 0.06,
                 f"本周总完成 {wp['done']}/{wp['total']}（{wp['rate'] * 100:.0f}%）",
                 ha="center", color="#cfe6ff", fontsize=18)
    save(fig, "f3_subject.png")

    # ---------- 帧 4：徽章墙 ----------
    fig = plt.figure(figsize=(16, 9), facecolor=BG)
    fig.text(0.5, 0.90, "徽章墙", ha="center",
             color="white", fontsize=30, fontweight="bold")
    ax = fig.add_axes([0.05, 0.08, 0.90, 0.74])
    ax.set_xlim(0, 4)
    ax.set_ylim(0, 2)
    ax.axis("off")
    badges = state["all_badges"]
    cols = 4
    for i, b in enumerate(badges):
        cx, cy = i % cols, 1 - (i // cols)
        x0, y0 = cx + 0.08, cy - 0.08
        face = GOLD if b["earned"] else "#2a3a52"
        edge = "#b58900" if b["earned"] else "#3a4a62"
        ax.add_patch(FancyBboxPatch(
            (x0, y0 - 0.62), 0.84, 0.62,
            boxstyle="round,pad=0.02,rounding_size=0.06",
            linewidth=2, edgecolor=edge, facecolor=face,
        ))
        ax.text(x0 + 0.42, y0 - 0.18, "★" if b["earned"] else "☆",
                ha="center", va="center", fontsize=30,
                color="#1a1a1a" if b["earned"] else "#cfe6ff")
        ax.text(x0 + 0.42, y0 - 0.40, b["badge_name"],
                ha="center", va="center", fontsize=15,
                color="#1a1a1a" if b["earned"] else "#cfe6ff",
                fontweight="bold")
        ax.text(x0 + 0.42, y0 - 0.56, "已解锁" if b["earned"] else "未解锁",
                ha="center", va="center", fontsize=12,
                color="#1a1a1a" if b["earned"] else "#9fb6d4")
    save(fig, "f4_badges.png")

    # ---------- 帧 5：结尾 ----------
    fig = plt.figure(figsize=(16, 9), facecolor=BG)
    fig.text(0.5, 0.62, "继续加油，下个里程碑见！", ha="center",
             color="white", fontsize=40, fontweight="bold")
    fig.text(0.5, 0.48,
             f"已积累 {state['points']} 积分 · 解锁 {len(earned)} 枚徽章 · 连续打卡 {state['streak']} 天",
             ha="center", color=ACCENT, fontsize=22)
    fig.text(0.5, 0.12, "工作学习一体化平台 · 奖励中心", ha="center",
             color=MUTE, fontsize=16)
    save(fig, "f5_end.png")

    # ---------- 合成 mp4 ----------
    clips = [ImageClip(f).with_duration(2.5) for f in frames]
    final = concatenate_videoclips(clips, method="compose")
    ts = today.strftime("%Y%m%d_%H%M%S")
    out_path = VIDEO_DIR / f"review_{ts}.mp4"
    final.write_videofile(str(out_path), fps=24, codec="libx264", audio=False)
    final.close()

    # 清理临时帧
    for f in frames:
        try:
            os.remove(f)
        except OSError:
            pass
    try:
        frame_dir.rmdir()
    except OSError:
        pass

    vid = db.insert_video(period_label, str(out_path), start, end)
    return {
        "id": vid,
        "title": period_label,
        "path": str(out_path),
        "period_start": start,
        "period_end": end,
        "file_url": f"/api/reward/video/{vid}/file",
    }
