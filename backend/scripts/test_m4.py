"""M4 分析引擎联调自测：覆盖 clarify→confirm→decompose→save→qa→qa-answer 全链路。"""
import json
import urllib.request

BASE = "http://127.0.0.1:8000/api"


def post(path, body):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=10) as r:
        return json.loads(r.read().decode())


print("== A clarify ==")
r = post("/analysis/clarify", {"text": "给周五客户会议准备一份周报"})
assert r["questions"], "clarify 未返回问题"
print(f"mock={r['mock']} questions={len(r['questions'])}")

print("== B confirm ==")
answers = [{"field": q["field"], "answer": f"答:{q['field']}"} for q in r["questions"]]
r = post("/analysis/confirm", {"text": "给周五客户会议准备一份周报", "answers": answers})
req = r["requirement"]
assert req and req.get("goal"), "confirm 未返回确认卡"
print(f"mock={r['mock']} requirement keys={list(req.keys())}")

print("== C decompose ==")
r = post("/analysis/decompose", {"requirement": req})
steps = r["steps"]
assert steps, "decompose 未返回步骤"
print(f"mock={r['mock']} steps={len(steps)}")

print("== D save ==")
r = post("/analysis/save", {"title": "客户周报", "requirement": req, "steps": steps})
task_id, plan_id = r["task_id"], r["plan_id"]
print(f"plan_id={plan_id} task_id={task_id} child_ids={r['child_ids']}")
assert len(r["child_ids"]) == len(steps), "子任务数与步骤数不一致"

print("== 验证 task 树落库 ==")
tree = get("/tasks")
root = next((t for t in tree if t["id"] == task_id), None)
assert root, "主任务未出现在任务树"
print(f"主任务 #{task_id} 子任务数={len(root.get('children', []))}")

print("== D-2 qa 三问 ==")
step = {"order": 1, "desc": "收集清单", "est_hours": 1, "deps": [], "need": ["任务系统"], "output": "清单"}
r = post(f"/analysis/{plan_id}/qa", {"step": step})
assert r["risks"] and r["blockers"] and r["prerequisites"], "qa 三问不完整"
print(f"mock={r['mock']} risks={r['risks'][:24]}…")

print("== D-3 qa-answer 沉淀 ==")
r = post(f"/analysis/{plan_id}/qa-answer", {
    "step_order": 1, "step_desc": "收集清单",
    "questions": {"risks": r["risks"], "blockers": r["blockers"], "prerequisites": r["prerequisites"]},
    "answers": {"risks": "已备份", "blockers": "无", "prerequisites": "已就绪"},
})
assert r["ok"] and len(r["qa_log"]) >= 1, "qa 沉淀失败"
print(f"ok={r['ok']} qa_log_len={len(r['qa_log'])}")

print("\n✅ M4 全链路联调通过")
