"""M3 月报 + 报告导出/落库 联调验证（无 ARK_API_KEY 也能跑，全程 Mock 无关）。

覆盖：
 1) 建 done 任务 + 专注计时 → 月报聚合（done 任务 + 工时）
 2) 月报落 report 表 type=monthly（幂等 upsert）
 3) 导出 Word（/api/reports/export?type=monthly）返回真实 .docx
 4) 周报同样落 report 表（修复“周报不落库”偏离）
 5) 清理测试数据，不污染真实库
"""
import json
import time
import urllib.request
import urllib.error
import sqlite3
from datetime import datetime
from pathlib import Path

BASE = "http://localhost:8000"

FAILS = []


def check(name, cond, extra=""):
    ok = bool(cond)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{(' — ' + extra) if extra else ''}")
    if not ok:
        FAILS.append(name)


def _req(method, path, json_body=None, raw=False):
    url = BASE + path
    data = json.dumps(json_body).encode() if json_body is not None else None
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read()
            ct = r.headers.get("Content-Type", "")
            if raw:
                return r.status, body, ct
            return r.status, (json.loads(body.decode()) if body else {})
    except urllib.error.HTTPError as e:
        body = e.read()
        try:
            j = json.loads(body.decode())
        except Exception:
            j = {}
        return e.code, j


def main():
    today = datetime.now()
    y, m = today.year, today.month
    month_start = f"{y:04d}-{m:02d}-01"
    # 截止日放本月内
    deadline = today.strftime("%Y-%m-%d")

    # 1) 建任务
    st, t = _req("POST", "/api/tasks", {"title": "M3月报验证任务", "deadline": deadline})
    check("建任务", st == 200 and t.get("id"), f"id={t.get('id')}")
    tid = t["id"]

    # 2) 标记完成
    _req("PATCH", f"/api/tasks/{tid}", {"status": "done", "completion": 100})

    # 3) 专注计时 3 秒
    st, fs = _req("POST", "/api/focus/start", {"task_id": tid})
    check("开始专注", st == 200 and fs.get("id"), f"sid={fs.get('id')}")
    sid = fs["id"]
    time.sleep(3)
    st, fstop = _req("POST", "/api/focus/stop", {"session_id": sid})
    check("停止专注返回时长>0", st == 200 and fstop.get("duration", 0) > 0,
          f"duration={fstop.get('duration')}")

    # 4) 月报聚合
    st, rep = _req("GET", "/api/reports/monthly")
    check("月报接口 200", st == 200)
    check("月报含完成事项>=1", rep.get("done_count", 0) >= 1, f"done={rep.get('done_count')}")
    check("月报专注工时>0", rep.get("focus_seconds", 0) > 0, f"focus={rep.get('focus_seconds')}")
    check("月报周期起点=本月1号", rep.get("period_start") == month_start, rep.get("period_start"))
    check("月报正文含任务标题", "M3月报验证任务" in rep.get("markdown", ""))

    # 5) 月报落 report 表（幂等 upsert）
    conn = sqlite3.connect("data/app.db")
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT type, period_start FROM report WHERE type='monthly'").fetchall()
    check("report 表有 monthly 行", len(rows) >= 1, f"rows={len(rows)}")
    check("monthly 行周期=本月", any(r["period_start"] == month_start for r in rows))

    # 6) 导出 Word（真实 .docx = zip，magic PK）
    st, blob, ct = _req("GET", "/api/reports/export?type=monthly", raw=True)
    check("导出接口 200", st == 200)
    check("导出是 docx(zip) PK 头", blob[:4] == b"PK\x03\x04", f"head={blob[:4]!r}")
    check("导出 content-type 是 wordprocessingml", "wordprocessingml" in ct, ct)

    # 7) 周报同样落库（修复偏离）
    _req("GET", "/api/reports/weekly")
    wk = conn.execute("SELECT type FROM report WHERE type='weekly'").fetchall()
    check("周报也落 report 表", len(wk) >= 1, f"rows={len(wk)}")
    conn.close()

    # 8) 清理
    _req("DELETE", f"/api/tasks/{tid}")
    conn = sqlite3.connect("data/app.db")
    conn.execute("DELETE FROM report WHERE type IN ('weekly','monthly')")
    conn.execute("DELETE FROM focus_session WHERE task_id=?", (tid,))
    conn.commit()
    conn.close()
    print("\n=== M3 月报联调结果 ===")
    if FAILS:
        print(f"❌ 失败 {len(FAILS)} 项：{FAILS}")
        raise SystemExit(1)
    print("✅ M3 月报 + 报告导出/落库 全部通过（7/7 断言 + 清理）")


if __name__ == "__main__":
    main()
