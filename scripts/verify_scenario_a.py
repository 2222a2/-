#!/usr/bin/env python3
"""场景 A 端到端走查脚本（Phase 1 验收）。

覆盖链路：命令面板一句话 → M4 分析引擎(澄清/确认/拆解/保存) → M3 任务树 →
M1 生成真实 Word → 模拟 OnlyOffice 编辑回存 → 标记任务完成 → M7 专注计时 →
自动进周报。

在 1–11 步基座上，额外覆盖 Phase 1 收尾四项新能力（与项目既有技术栈/约束一致）：
  - ① 报告聚合补文档维度：周报/月报含「本周期文档」段与 doc_count；
  - ② 防空洞任务提醒：/api/tasks/stale 命中久未更新任务，完成后不再命中；
  - ③ M7 番茄钟时长配置：/api/settings/focus 读写并落库复用；
  - ④ 报告导出补 PDF：/api/reports/export?format=docx|pdf 返回真实 .docx/.pdf。

每步断言，结尾清理本脚本产生的测试数据（不影响真实业务数据）。

运行前置：
  - 后端已在 BASE_URL 运行（默认 http://localhost:8000，可用环境变量覆盖）。
  - 未配 ARK_API_KEY 也能跑：各 AI 环节走 Mock 兜底，与"无 key 演示"一致。
用法：
  cd backend
  .venv2/Scripts/python.exe ../scripts/verify_scenario_a.py
"""
import os, sys, json, time, shutil, sqlite3, socket, threading, tempfile
import http.server
import urllib.request, urllib.error
from pathlib import Path

BASE = os.environ.get("BASE_URL", "http://localhost:8000")
DATA = Path("data")
DOCS = DATA / "docs"
DB = DATA / "app.db"

FAILS = []
COUNT = 0


def check(name, cond, extra=""):
    global COUNT
    COUNT += 1
    ok = bool(cond)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{(' — ' + extra) if extra else ''}")
    if not ok:
        FAILS.append(name)


def _req(method, path, json_body=None):
    url = BASE + path
    data = json.dumps(json_body).encode("utf-8") if json_body is not None else None
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read()
            try:
                return r.status, json.loads(raw.decode("utf-8"))
            except Exception:
                return r.status, raw          # 二进制响应（如 .docx 文件）原样返回
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            body = json.loads(raw.decode("utf-8", "ignore"))
        except Exception:
            body = raw
        return e.code, body


def post(path, body): return _req("POST", path, body)
def get(path): return _req("GET", path)
def patch(path, body): return _req("PATCH", path, body)
def put(path, body): return _req("PUT", path, body)
def delete(path): return _req("DELETE", path)


# —— 临时 HTTP 服务：模拟 OnlyOffice 回存时后端去下载的“编辑后文件” ——
class _Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(_SERVE_DIR), **k)
    def log_message(self, *a):
        pass


_SERVE_DIR = None
_httpd = None


def serve_file(src_path):
    global _SERVE_DIR, _httpd
    _SERVE_DIR = tempfile.mkdtemp(prefix="oo_cb_")
    shutil.copy(src_path, Path(_SERVE_DIR) / "edited.docx")
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    _httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    threading.Thread(target=_httpd.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{port}/edited.docx"


def stop_serve():
    if _httpd:
        _httpd.shutdown()


created_task_ids = []
created_doc_ids = []
created_session_ids = []


def main():
    # 0. 健康检查
    st, h = get("/api/health")
    check("后端健康检查 /api/health", st == 200, f"status={st}")
    if st != 200:
        print("后端未就绪，请先启动后端（BASE_URL=%s）。" % BASE)
        sys.exit(2)

    # 1. 命令面板入口
    st, c = post("/api/ai/command", {"text": "准备周五客户周报"})
    check("命令面板入口 /api/ai/command 可达", st == 200 and "action" in c, f"action={c.get('action')}")
    print(f"     ↳ 实际路由 action={c.get('action')}（注：'周报'关键词当前走 gen_report；"
          f"场景A的'分析拆解'由 M4 分析引擎承载，见验收说明）")

    # 2. M4 澄清
    st, cl = post("/api/analysis/clarify", {"text": "准备周五客户周报"})
    qs = cl.get("questions", [])
    check("M4 澄清返回反问问题", st == 200 and len(qs) >= 1, f"{len(qs)} 个问题")
    answers = [{"field": q.get("field", "goal"),
                "answer": f"答复：{q.get('question','')}"} for q in qs]

    # 3. M4 确认卡
    st, cf = post("/api/analysis/confirm", {"text": "准备周五客户周报", "answers": answers})
    req = cf.get("requirement", {})
    check("M4 确认卡含 goal", st == 200 and req.get("goal"), f"goal={req.get('goal','')[:24]}")

    # 4. M4 拆解
    st, dc = post("/api/analysis/decompose", {"requirement": req})
    steps = dc.get("steps", [])
    check("M4 拆解返回步骤", st == 200 and len(steps) >= 1, f"{len(steps)} 步")

    # 5. M4 保存 → 写 M3 任务
    st, sv = post("/api/analysis/save",
                  {"title": "周五客户周报", "requirement": req, "steps": steps})
    task_id = sv.get("task_id"); child_ids = sv.get("child_ids", []); plan_id = sv.get("plan_id")
    check("M4 保存 → 主任务/子任务/plan",
          st == 200 and task_id and len(child_ids) == len(steps) and plan_id,
          f"task={task_id} children={len(child_ids)} plan={plan_id}")
    created_task_ids.append(task_id)

    # 6. M3 任务树验证
    st, tree = get("/api/tasks")
    flat = []
    def _walk(ns):
        for n in ns:
            flat.append(n); _walk(n.get("children", []))
    _walk(tree)
    ids = {t["id"] for t in flat}
    check("M3 任务树含主任务与全部子任务",
          task_id in ids and set(child_ids).issubset(ids),
          f"主={task_id} 子全覆盖={set(child_ids).issubset(ids)}")

    # 7. M1 生成 Word
    st, g = post("/api/docs/generate",
                 {"prompt": "客户周报", "doc_type": "word", "linked_task_id": task_id,
                  "source": "analysis", "requirement": req, "steps": steps})
    doc = g.get("doc", {})
    doc_id = doc.get("id")
    check("M1 生成 Word 返回 doc",
          st == 200 and doc_id and doc.get("type") == "word" and doc.get("linked_task_id") == task_id,
          f"doc={doc_id} linked={doc.get('linked_task_id')}")
    created_doc_ids.append(doc_id)
    docx = DOCS / f"{doc_id}.docx"
    check("M1 真实 .docx 文件落盘", docx.exists(), str(docx))

    # 8. OnlyOffice 回存（模拟）
    url = serve_file(docx)
    st, cb = post(f"/api/docs/callback/{doc_id}", {"status": 2, "url": url})
    check("OnlyOffice 回调回存返回 error=0", st == 200 and cb.get("error") == 0, f"body={cb}")
    stop_serve()
    st, vs = get(f"/api/docs/{doc_id}/versions")
    check("回存后版本升到 v2", st == 200 and vs.get("current_version") == 2,
          f"version={vs.get('current_version')}")
    st, f = get(f"/api/docs/file/{doc_id}")
    check("文件服务可拉取当前版", st == 200, f"status={st}")

    # 9. 标记完成（先完成子任务以验证父完成度汇总，再标记主任务）
    #    注意：父完成度由子任务的 completion 字段汇总（非 status），故子任务需置 completion=100
    for cid in child_ids:
        patch(f"/api/tasks/{cid}", {"status": "done", "completion": 100})
    st, t = get(f"/api/tasks/{task_id}")
    check("M3 父完成度随子任务汇总=100", st == 200 and t.get("completion") == 100,
          f"completion={t.get('completion')}")
    patch(f"/api/tasks/{task_id}", {"status": "done"})
    st, t2 = get(f"/api/tasks/{task_id}")
    check("M3 主任务标记完成", st == 200 and t2.get("status") == "done", f"status={t2.get('status')}")

    # 10. M7 专注计时
    st, fs = post("/api/focus/start", {"task_id": task_id})
    sid = fs.get("id")
    check("M7 专注开始返回 session", st == 200 and sid, f"sid={sid}")
    created_session_ids.append(sid)
    time.sleep(3)
    st, fo = post("/api/focus/stop", {"session_id": sid})
    dur = fo.get("duration", 0)
    check("M7 专注停止算出时长>=3s", st == 200 and dur >= 3, f"duration={dur}")

    # 11. 周报聚合
    st, rep = get("/api/reports/weekly")
    check("周报聚合专注工时>0", st == 200 and rep.get("focus_seconds", 0) > 0,
          f"focus_seconds={rep.get('focus_seconds')}")
    check("周报统计到已完成任务", rep.get("done_count", 0) >= 1,
          f"done_count={rep.get('done_count')}")
    check("周报专注工时>=本次专注时长", rep.get("focus_seconds", 0) >= dur,
          f"focus={rep.get('focus_seconds')} dur={dur}")
    print("     ↳ 周报 Markdown 片段：")
    for line in rep.get("markdown", "").splitlines()[:6]:
        print("        " + line)

    # 11b. 报告聚合补文档维度（新能力①，审计 #7）
    #      M1 在 step7 已生成 linked_task_id=task_id 的 Word，created_at=now 落在本周/本月，
    #      故周报/月报应聚合到该文档（doc_count>=1，Markdown 含「本周期文档」段）。
    st, mrep = get("/api/reports/monthly")
    check("周报含文档维度 doc_count>=1",
          rep.get("doc_count", 0) >= 1,
          f"doc_count={rep.get('doc_count')}")
    check("周报 Markdown 含『本周期文档』段",
          "本周期文档" in rep.get("markdown", ""),
          "本周期文档" in rep.get("markdown", "") and "OK" or "段缺失")
    check("月报含文档维度 doc_count>=1", st == 200 and mrep.get("doc_count", 0) >= 1,
          f"status={st} doc_count={mrep.get('doc_count')}")
    check("月报 Markdown 含『本周期文档』段",
          "本周期文档" in mrep.get("markdown", ""),
          "本周期文档" in mrep.get("markdown", "") and "OK" or "段缺失")

    # 12. 防空洞任务提醒（新能力②，计划 §5.4 P1）
    st, stale_c = post("/api/tasks", {
        "title": "【走查】防空洞示例任务",
        "description": None, "deadline": None,
        "urgency": False, "importance": False, "parent_id": None,
    })
    stale_id = stale_c.get("id")
    check("防空洞：创建测试任务", st == 200 and stale_id, f"id={stale_id}")
    # 把 updated_at 回拨到 8 天前，使其成为「久未更新」任务
    conn = sqlite3.connect(str(DB))
    conn.execute("UPDATE task SET updated_at = datetime('now','-8 days') WHERE id=?", (stale_id,))
    conn.commit(); conn.close()
    st, stale = get("/api/tasks/stale?days=7")
    stale_ids = [t["id"] for t in stale]
    check("防空洞：/api/tasks/stale 命中 8 天前任务",
          st == 200 and stale_id in stale_ids,
          f"命中 {len(stale)} 个，含目标={stale_id in stale_ids}")
    # 标记完成后，应不再被判定为防空洞
    patch(f"/api/tasks/{stale_id}", {"status": "done"})
    st, stale2 = get("/api/tasks/stale?days=7")
    stale2_ids = [t["id"] for t in stale2]
    check("防空洞：标记完成后不再命中", stale_id not in stale2_ids,
          f"仍命中={stale_id in stale2_ids}")
    created_task_ids.append(stale_id)   # 统一随脚本末尾清理

    # 13. M7 番茄钟时长配置（新能力③，M7 缺口 P1）
    st, pre = get("/api/settings/focus")
    check("番茄钟：默认配置可读",
          st == 200 and "work_minutes" in pre and "break_minutes" in pre,
          f"work={pre.get('work_minutes')} break={pre.get('break_minutes')}")
    st, up = put("/api/settings/focus", {"work_minutes": 50, "break_minutes": 10})
    check("番茄钟：PUT 保存新时长",
          st == 200 and up.get("work_minutes") == 50 and up.get("break_minutes") == 10,
          f"work={up.get('work_minutes')} break={up.get('break_minutes')}")
    st, re = get("/api/settings/focus")
    check("番茄钟：持久化后再次读取一致",
          re.get("work_minutes") == 50 and re.get("break_minutes") == 10,
          f"work={re.get('work_minutes')} break={re.get('break_minutes')}")
    # 还原默认值，避免污染真实偏好
    put("/api/settings/focus",
        {"work_minutes": pre.get("work_minutes"), "break_minutes": pre.get("break_minutes")})

    # 14. 报告导出补 PDF（新能力④，审计 #5 扩展）
    st, docx_bytes = get("/api/reports/export?type=weekly&format=docx")
    is_docx = (st == 200 and isinstance(docx_bytes, (bytes, bytearray))
               and bytes(docx_bytes[:2]) == b"PK")   # .docx 是 zip，以 PK 开头
    check("导出 Word：返回真实 .docx（PK 头）", is_docx,
          f"status={st} len={len(docx_bytes) if isinstance(docx_bytes,(bytes,bytearray)) else 'n/a'}")
    st, pdf_bytes = get("/api/reports/export?type=weekly&format=pdf")
    is_pdf = (st == 200 and isinstance(pdf_bytes, (bytes, bytearray))
              and bytes(pdf_bytes[:5]) == b"%PDF-")
    check("导出 PDF：返回真实 .pdf（%PDF 头）", is_pdf,
          f"status={st} head={bytes(pdf_bytes[:8]) if isinstance(pdf_bytes,(bytes,bytearray)) else 'n/a'}")

    # —— 清理测试数据 ——
    print("\n=== 清理本脚本产生的测试数据 ===")
    try:
        for tid in created_task_ids:
            delete(f"/api/tasks/{tid}")          # 级联删子任务
        conn = sqlite3.connect(str(DB))
        if created_doc_ids:
            conn.execute("DELETE FROM doc WHERE id IN (%s)" %
                         ",".join("?" * len(created_doc_ids)), created_doc_ids)
        if created_session_ids:
            conn.execute("DELETE FROM focus_session WHERE id IN (%s)" %
                         ",".join("?" * len(created_session_ids)), created_session_ids)
        conn.commit(); conn.close()
        for did in created_doc_ids:
            (DOCS / f"{did}.docx").unlink(missing_ok=True)
            shutil.rmtree(DOCS / "snapshots" / str(did), ignore_errors=True)
        print(f"已清理 task={created_task_ids} doc={created_doc_ids} session={created_session_ids}")
    except Exception as e:
        print(f"[WARN] 清理异常（如需可手动清理）：{e}")

    print("\n=== 场景 A 走查结果 ===")
    if FAILS:
        print(f"❌ 失败 {len(FAILS)} 项：{FAILS}")
        sys.exit(1)
    print(f"✅ 场景 A 端到端走查全部通过（共 {COUNT} 项断言）")


if __name__ == "__main__":
    main()
