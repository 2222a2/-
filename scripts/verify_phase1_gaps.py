"""Phase 1 收尾四项（文档维度 / 防空洞 / 番茄钟配置 / PDF 导出）集成验证。

隔离策略：把 config.DATA_DIR / DB_PATH 指向临时目录，import 应用后只用临时库，
绝不污染真实 app.db。起一个 uvicorn 测试后端（8000），用 urllib 打真实接口做端到端断言。
"""
import os
import sys
import json
import time
import tempfile
import threading
import sqlite3
import urllib.request
import urllib.error
from pathlib import Path

PROJ = r"C:\Users\用户\worklearn-platform\backend"
sys.path.insert(0, PROJ)

# 1) 先覆盖配置到临时目录，再 import 应用（app 模块在 import 时绑定 config.DB_PATH）
import app.config as cfg

TMP = tempfile.mkdtemp(prefix="wl_verify_")
cfg.DATA_DIR = Path(TMP)
cfg.DOCS_DIR = Path(TMP) / "docs"
cfg.DB_PATH = Path(TMP) / "app.db"
cfg.DOCS_DIR.mkdir(parents=True, exist_ok=True)
# 避免任何外部 AI/网络依赖
os.environ.setdefault("ARK_API_KEY", "")
os.environ.setdefault("RAG_BACKEND", "fts")

import app.db as db
import app.main as main_mod

db.init_db()
app = main_mod.app

import uvicorn

BASE = "http://127.0.0.1:8000"


def _server():
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8000, log_level="warning"))
    srv.run()


def req(method: str, path: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method,
                               headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            raw = resp.read()
            ct = resp.headers.get("Content-Type", "")
            return resp.status, ct, raw
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), e.read()


PASS = 0
FAIL = 0


def check(name: str, cond: bool, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {extra}")


print("启动测试后端 ...")
t = threading.Thread(target=_server, daemon=True)
t.start()
time.sleep(3)

# 健康检查
st, ct, raw = req("GET", "/api/health")
check("health 200", st == 200, f"status={st}")

# ---------- 1. 报告聚合补文档维度 ----------
print("\n[1] 报告聚合补文档维度")
r = req("POST", "/api/tasks", {"title": "verify done task 文档维度"})
tid = json.loads(r[2])["id"]
req("PATCH", f"/api/tasks/{tid}", {"status": "done", "completion": 100})
# 插入一个本周期文档（linked_task_id 指向该任务）
did = db.insert_doc(str(cfg.DOCS_DIR / "verify_weekly.docx"), "word", linked_task_id=tid)

st, ct, raw = req("GET", "/api/reports/weekly")
body = json.loads(raw)
check("周报 200", st == 200)
check("周报 doc_count>=1", body.get("doc_count", 0) >= 1, f"doc_count={body.get('doc_count')}")
check("周报 markdown 含『本周期文档』", "## 本周期文档" in body["markdown"])
check("周报 markdown 含文档名", "verify_weekly.docx" in body["markdown"])
check("周报 done_count>=1", body.get("done_count", 0) >= 1, f"done={body.get('done_count')}")

st, ct, raw = req("GET", "/api/reports/monthly")
body = json.loads(raw)
check("月报 doc_count>=1", body.get("doc_count", 0) >= 1, f"doc_count={body.get('doc_count')}")
check("月报 markdown 含『本周期文档』", "## 本周期文档" in body["markdown"])

# ---------- 2. 防空洞任务提醒 ----------
print("\n[2] 防空洞任务提醒")
r = req("POST", "/api/tasks", {"title": "verify stale task"})
sid = json.loads(r[2])["id"]
# 直接把该任务的 updated_at 拨到 30 天前
conn = sqlite3.connect(str(cfg.DB_PATH))
conn.execute("UPDATE task SET updated_at = datetime('now','-30 days') WHERE id=?", (sid,))
conn.commit()
conn.close()

st, ct, raw = req("GET", "/api/tasks/stale")
items = json.loads(raw)
ids = [x["id"] for x in items]
check("stale 接口 200", st == 200)
check("久未更新任务被识别", sid in ids, f"ids={ids}")
stale = next((x for x in items if x["id"] == sid), None)
check("days_since≈30", stale is not None and 25 <= stale["days_since"] <= 35, f"days={stale}")

# 已完成任务不应出现在 stale
r = req("POST", "/api/tasks", {"title": "verify fresh done"})
fid = json.loads(r[2])["id"]
req("PATCH", f"/api/tasks/{fid}", {"status": "done", "completion": 100})
st, ct, raw = req("GET", "/api/tasks/stale")
items = json.loads(raw)
check("已完成任务不在 stale", fid not in [x["id"] for x in items])

# ---------- 3. 番茄钟时长配置 ----------
print("\n[3] 番茄钟时长配置（落库复用）")
st, ct, raw = req("GET", "/api/settings/focus")
prefs = json.loads(raw)
check("默认 work=25/break=5", prefs["work_minutes"] == 25 and prefs["break_minutes"] == 5, f"{prefs}")

st, ct, raw = req("PUT", "/api/settings/focus", {"work_minutes": 30, "break_minutes": 10})
prefs = json.loads(raw)
check("PUT 返回 30/10", prefs["work_minutes"] == 30 and prefs["break_minutes"] == 10, f"{prefs}")

st, ct, raw = req("GET", "/api/settings/focus")
prefs = json.loads(raw)
check("落库后再次 GET 仍为 30/10", prefs["work_minutes"] == 30 and prefs["break_minutes"] == 10, f"{prefs}")

# ---------- 4. 报告导出补 PDF ----------
print("\n[4] 报告导出 Word / PDF")
st, ct, raw = req("GET", "/api/reports/export?type=weekly&format=docx")
check("Word 导出 200", st == 200, f"status={st}")
check("Word content-type", "wordprocessingml" in ct, ct)
check("Word 文件头 PK", raw[:2] == b"PK")

st, ct, raw = req("GET", "/api/reports/export?type=monthly&format=pdf")
check("PDF 导出 200", st == 200, f"status={st}")
check("PDF content-type", "application/pdf" in ct, ct)
check("PDF 文件头 %PDF", raw[:4] == b"%PDF")

# 清理临时库
import shutil
try:
    shutil.rmtree(TMP)
except Exception:
    pass

print(f"\n==== 结果：{PASS} PASS / {FAIL} FAIL ====")
sys.exit(1 if FAIL else 0)
