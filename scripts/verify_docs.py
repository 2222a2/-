"""M1 文档中心联调验证脚本（独立进程，打真实运行的后端）。
验证闭环：生成 Word 周报 -> 模拟 OnlyOffice 编辑回存 -> 版本快照 -> 文件服务 -> 回滚。
"""
import http.server
import json
import threading
from pathlib import Path

import httpx
from docx import Document

BASE = "http://localhost:8000"
DATA = Path(__file__).resolve().parent.parent / "backend" / "data"
SERVE_PORT = 8099

ok = []


def check(name, cond, extra=""):
    ok.append(cond)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {extra}")


# 1) 生成 Word 周报 ----------------------------------------------------------
r = httpx.post(f"{BASE}/api/docs/generate", json={
    "prompt": "本周工作周报", "doc_type": "word", "title": "测试周报",
}, timeout=30)
check("generate 200", r.status_code == 200, f"({r.status_code})")
data = r.json()
doc_id = data["doc"]["id"]
cfg = data["editor_config"]
print(f"  -> doc_id={doc_id}, file_url={cfg['document']['url']}, callback={cfg['editorConfig']['callbackUrl']}")
check("返回 editor_config 含 file_url/callback",
      cfg["document"]["url"].endswith(f"/api/docs/file/{doc_id}")
      and cfg["editorConfig"]["callbackUrl"].endswith(f"/api/docs/callback/{doc_id}"))
check("文档有 document.key", bool(cfg["document"].get("key")))

# 2) 真实文件落盘 + Doc 表 ------------------------------------------------
doc_path = DATA / "docs" / f"{doc_id}.docx"
check("真实 .docx 落盘", doc_path.exists())
# 验证是真的 docx 且能解析
d1 = Document(str(doc_path))
text1 = "\n".join(p.text for p in d1.paragraphs)
check("docx 可解析且有内容", len(text1) > 0, f"(len={len(text1)})")
check("初始版本 v1", data["doc"]["current_version"] == 1)

# 3) 模拟 OnlyOffice 编辑回存（改一字）-------------------------------------
# 3a) 制作“改动版”docx：在第一个有内容的段落末尾加标记
changed = None
for p in d1.paragraphs:
    if p.text.strip():
        p.text = p.text + "【已编辑】"
        changed = p.text
        break
edited_path = DATA / f"edited_{doc_id}.docx"
d1.save(str(edited_path))


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/edited.docx"):
            body = edited_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404); self.end_headers()

    def log_message(self, *a):  # 静默
        pass


srv = http.server.HTTPServer(("127.0.0.1", SERVE_PORT), Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()

# 3b) 触发回调（OnlyOffice 在 status=2 时把编辑后文件挂到 url）
cb = httpx.post(f"{BASE}/api/docs/callback/{doc_id}", json={
    "status": 2, "url": f"http://127.0.0.1:{SERVE_PORT}/edited.docx",
}, timeout=30)
check("callback 返回 error=0", cb.json().get("error") == 0, str(cb.json()))
srv.shutdown()

# 3c) 验证本地文件已被回存、内容变更
d2 = Document(str(doc_path))
text2 = "\n".join(p.text for p in d2.paragraphs)
check("回存后文件含改动标记", "【已编辑】" in text2, f"(changed='{changed}')")
check("回存后内容与初版不同", text1 != text2)

# 4) 版本快照 ---------------------------------------------------------------
v = httpx.get(f"{BASE}/api/docs/{doc_id}/versions", timeout=30)
versions = v.json()["versions"]
print(f"  版本列表: {json.dumps(versions, ensure_ascii=False)}")
check("当前版本 >=2", v.json()["current_version"] >= 2)
check("v2 快照文件存在", (DATA / "docs" / "snapshots" / str(doc_id) / "v2.docx").exists())

# 5) 文件服务 ---------------------------------------------------------------
fs = httpx.get(f"{BASE}/api/docs/file/{doc_id}", timeout=30)
check("文件服务 200 且字节一致", fs.status_code == 200 and fs.content == doc_path.read_bytes())

# 6) 回滚到 v1 --------------------------------------------------------------
# 先再改一次制造 v3，再回滚到 v1，验证 current 回到 v1 内容
rb = httpx.post(f"{BASE}/api/docs/{doc_id}/rollback/1", timeout=30)
check("rollback 200", rb.status_code == 200, f"({rb.status_code})")
d3 = Document(str(doc_path))
text3 = "\n".join(p.text for p in d3.paragraphs)
check("回滚后文件 == v1 内容", text3 == text1)
check("回滚产生新版本(v3)", rb.json()["doc"]["current_version"] == 3)

# 清理临时文件
try:
    edited_path.unlink()
except OSError:
    pass

print("\n==== 结论 ====")
print("PASS" if all(ok) else "FAIL", f"({sum(ok)}/{len(ok)})")
