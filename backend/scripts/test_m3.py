"""M3 后端联调自测：用标准库 urllib 调本地接口，验证任务 CRUD + 完成度汇总 + 周报。
运行：backend> .venv2/Scripts/python.exe scripts/test_m3.py  （需后端已起在 8000）
"""
import json
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:8000"


def req(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(r, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode() or "null")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except Exception as e:  # noqa: BLE001
        return -1, str(e)


print("1) health:", req("GET", "/api/health"))

s, parent = req("POST", "/api/tasks", {"title": "M3父任务-写周报", "importance": 1, "urgency": 1})
pid = parent["id"]
print("2) create parent:", s, "id=", pid)

_, c1 = req("POST", "/api/tasks", {"title": "子1-收集数据", "parent_id": pid})
_, c2 = req("POST", "/api/tasks", {"title": "子2-排版", "parent_id": pid})
print("3) create children:", c1["id"], c2["id"])

s, tree = req("GET", "/api/tasks")
for t in tree:
    if t["id"] == pid:
        print("4) parent completion (before, should be 0):", t["completion"], "| children:", len(t["children"]))

req("PATCH", f"/api/tasks/{c1['id']}", {"status": "done", "completion": 100})
s, tree = req("GET", "/api/tasks")
for t in tree:
    if t["id"] == pid:
        print("5) parent completion (after 1 done, should be 50):", t["completion"])

req("PATCH", f"/api/tasks/{c2['id']}", {"status": "done", "completion": 100})
s, tree = req("GET", "/api/tasks")
for t in tree:
    if t["id"] == pid:
        print("6) parent completion (after 2 done, should be 100):", t["completion"])

s, rep = req("GET", "/api/reports/weekly")
print("7) weekly done_count:", rep.get("done_count"), "| focus_seconds:", rep.get("focus_seconds"))
print("   weekly markdown head:", rep.get("markdown", "")[:90].replace("\n", " "))

s, d = req("DELETE", f"/api/tasks/{pid}")
print("8) delete parent (cascade):", s, d)
s, tree = req("GET", "/api/tasks")
print("9) remaining roots:", len(tree))
