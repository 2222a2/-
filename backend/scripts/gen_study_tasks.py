#!/usr/bin/env python3
"""备考任务生成器（P1 写库 + P3 手机推送发射源）。

做什么：
1. 读一份“每日模板”（DEFAULT_TEMPLATE，下面自行改），按目标日期生成任务；
2. 写入 worklearn-platform：优先 POST 到后端 API；后端没开就落盘
   backend/data/study_tasks_pending.json，等平台启动自动吃回（不丢）；
3. 发手机推送：只列“科目”摘要 + 平台页链接（链接用 STUDY_WEB_BASE_URL）。
   推送通道自动选：企业微信群机器人 > 方糖 ServerChan > 推送加 pushplus > Bark。
   只要设了其中任一的 key/地址即可，都不设则跳过推送。

用法：
  python gen_study_tasks.py                 # 默认生成“明天”，发推送
  python gen_study_tasks.py --date 2026-10-17
  python gen_study_tasks.py --dry-run       # 只打印，不写库不发推送
  python gen_study_tasks.py --no-wechat     # 写库但不发推送

依赖：仅标准库（urllib / json / datetime / pathlib），随便哪个 Python 都能跑。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

# ---------- 路径（脚本在 backend/scripts/，数据在 backend/data/）----------
HERE = Path(__file__).resolve().parent
DATA_DIR = HERE.parent / "data"
PENDING_FILE = DATA_DIR / "study_tasks_pending.json"

# ---------- 可配置项（按需改这里就行）----------
API_BASE = os.getenv("STUDY_API_BASE", "http://127.0.0.1:8000/api")
WEB_BASE = os.getenv("STUDY_WEB_BASE_URL", "http://127.0.0.1:5173")
WEBHOOK_FILE = DATA_DIR / ".wechat_webhook.txt"   # 企业微信机器人地址（可选通道之一）
WEBHOOK_ENV = os.getenv("WECHAT_WEBHOOK", "")
# 备选推送通道（任选其一，都不设则跳过推送）：
#  - SERVERCHAN_KEY：方糖，推到个人微信（关注公众号）。key 形如 SCTxxxx
#  - PUSHPLUS_TOKEN：推送加，推到个人微信（关注公众号）
#  - BARK_URL：Bark（仅 iOS），形如 https://api.day.app/你的KEY，点通知直接跳链接
SERVERCHAN_KEY = os.getenv("SERVERCHAN_KEY", "")
PUSHPLUS_TOKEN = os.getenv("PUSHPLUS_TOKEN", "")
BARK_URL = os.getenv("BARK_URL", "")
# 若后端开了口令保护（STUDY_PAGE_TOKEN），生成器写库时也得带，否则 401
API_TOKEN = os.getenv("STUDY_PAGE_TOKEN", "")

# 科目代码 -> 中文（用于微信摘要，避免暴露时间段细节）
SUBJECT_LABELS = {
    "math": "数学",
    "english": "英语",
    "cs408": "408",
    "ds": "数据结构",
    "other": "其他",
}

# ★ 每日模板：按郭郭 2026-08-28 作息 + 山大软工学硕备考科目（英语一/数学一/408）整理的草稿。
#   period 取值 morning/noon/evening。这是按长期记忆推断的初版，请按你的真实每日安排调整！
#   改这里就能改“每天该学啥”。
DEFAULT_TEMPLATE = [
    {"period": "morning", "subject": "english", "title": "早上英语：背词20个 + 跟读/音标 30min"},
    {"period": "noon",    "subject": "english", "title": "午休英语：可理解输入 15min（BBC 6 Minute / 书虫）"},
    {"period": "evening", "subject": "math",    "title": "晚上主课：数学一 60min"},
    {"period": "evening", "subject": "cs408",   "title": "晚上保温：408 复习 30min"},
    {"period": "evening", "subject": "ds",      "title": "晚上保温：数据结构 20min"},
]


def target_date(arg: str | None) -> str:
    if arg:
        return arg
    return (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")


def build_items(template) -> list[dict]:
    items = []
    for i, t in enumerate(template):
        items.append({
            "period": t.get("period"),
            "subject": t.get("subject"),
            "title": t["title"],
            "done": 0,
            "source": "auto",
            "sort_order": i,
        })
    return items


def post_api(date: str, items: list[dict]) -> bool:
    """POST 到后端 /api/study-tasks。成功返回 True。"""
    payload = json.dumps({"date": date, "items": items}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if API_TOKEN:
        headers["X-Study-Token"] = API_TOKEN
    req = urllib.request.Request(
        f"{API_BASE}/study-tasks",
        data=payload,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status == 200
    except Exception as e:
        print(f"[gen] 后端未在线（{e}），改为落盘 pending")
        return False


def write_pending(date: str, items: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    entries = []
    if PENDING_FILE.exists():
        try:
            entries = json.loads(PENDING_FILE.read_text(encoding="utf-8"))
        except Exception:
            entries = []
    # 同日期只保留最新一份
    entries = [e for e in entries if e.get("date") != date]
    entries.append({"date": date, "items": items})
    PENDING_FILE.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[gen] 已落盘 pending：{PENDING_FILE}（平台启动后会自动入库）")


def _post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read().decode("utf-8"))


def _post_form(url: str, payload: dict) -> dict:
    data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read().decode("utf-8"))


def _build_content(date: str, items: list[dict]):
    """仅科目摘要（去重、保模板顺序）+ 平台页链接。返回 (plain, md, title, link)。"""
    seen, subs = set(), []
    for it in items:
        s = it.get("subject") or "other"
        if s not in seen:
            seen.add(s)
            subs.append(SUBJECT_LABELS.get(s, s))
    weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][
        datetime.strptime(date, "%Y-%m-%d").weekday()
    ]
    link = f"{WEB_BASE.rstrip('/')}/study-tasks?date={date}"
    title = f"明日备考：{' · '.join(subs)}"
    plain = (
        f"📅 明日（{weekday} {date[5:]}）备考科目：\n"
        f"{' · '.join(subs)}\n"
        f"👉 点此查看/编辑：{link}"
    )
    md = f"📅 **明日（{weekday} {date[5:]}）备考科目**\n\n{' · '.join(subs)}\n\n👉 [点此查看/编辑]({link})"
    return plain, md, title, link


def send_notify(date: str, items: list[dict]) -> bool:
    """按可用配置自动选推送通道：企业微信 > 方糖 > 推送加 > Bark。都不设则跳过。"""
    plain, md, title, link = _build_content(date, items)
    webhook = WEBHOOK_ENV or (WEBHOOK_FILE.read_text(encoding="utf-8").strip() if WEBHOOK_FILE.exists() else "")

    if webhook:
        try:
            resp = _post_json(webhook, {"msgtype": "text", "text": {"content": plain}})
            ok = resp.get("errcode", 0) == 0
            print(f"[gen] 企业微信推送{'成功' if ok else '失败'}：{resp}")
            return ok
        except Exception as e:
            print(f"[gen] 企业微信推送异常：{e}")
            return False

    if SERVERCHAN_KEY:
        try:
            resp = _post_form(f"https://sctapi.ftqq.com/{SERVERCHAN_KEY}.send", {"title": title, "desp": md})
            ok = resp.get("code", 1) == 0
            print(f"[gen] 方糖推送{'成功' if ok else '失败'}：{resp}")
            return ok
        except Exception as e:
            print(f"[gen] 方糖推送异常：{e}")
            return False

    if PUSHPLUS_TOKEN:
        try:
            resp = _post_json("http://www.pushplus.plus/send",
                             {"token": PUSHPLUS_TOKEN, "title": title, "content": md, "contentType": "markdown"})
            ok = resp.get("code", 1) == 200
            print(f"[gen] 推送加{'成功' if ok else '失败'}：{resp}")
            return ok
        except Exception as e:
            print(f"[gen] 推送加异常：{e}")
            return False

    if BARK_URL:
        try:
            burl = BARK_URL.rstrip("/") + "/push"
            resp = _post_json(burl, {"title": title, "body": plain, "url": link})
            ok = (resp.get("code") == 200) or ("success" in str(resp).lower())
            print(f"[gen] Bark 推送{'成功' if ok else '失败'}：{resp}")
            return ok
        except Exception as e:
            print(f"[gen] Bark 推送异常：{e}")
            return False

    print("[gen] 未配置任何推送通道（企业微信/方糖/推送加/Bark），跳过推送")
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="目标日期 YYYY-MM-DD，默认明天")
    ap.add_argument("--dry-run", action="store_true", help="只打印，不写库不发微信")
    ap.add_argument("--no-wechat", action="store_true", help="写库但不发微信")
    args = ap.parse_args()

    date = target_date(args.date)
    items = build_items(DEFAULT_TEMPLATE)
    print(f"[gen] 目标日期 {date}，模板 {len(items)} 条：")
    for it in items:
        print(f"      [{it['period']}] {SUBJECT_LABELS.get(it['subject'] or 'other', it['subject'])} - {it['title']}")

    if args.dry_run:
        print("[gen] --dry-run：跳过写库与推送")
        return 0

    if not post_api(date, items):
        write_pending(date, items)

    if not args.no_wechat:
        send_notify(date, items)

    return 0


if __name__ == "__main__":
    sys.exit(main())
