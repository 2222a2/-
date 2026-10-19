"""M2 离线自测：不依赖网络/密钥，验证工具循环 + DB 落地。

跑法：backend> .venv/Scripts/python.exe scripts/test_m2.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db
from app.ai.provider import MockProvider, get_provider
from app.ai.agent import run_agent
from app.ai.tools import registry

db.init_db()


def log(title, payload):
    print(f"\n=== {title} ===")
    print(payload)


provider = get_provider()
log("provider (应为 MockProvider，因无 ARK_API_KEY)", provider.name)

log("已注册工具", registry.names())

# 1) 记笔记 -> remember -> 写 knowledge_card + search_index
r1 = run_agent("记一下 明天下午三点要交季度报告", provider)
log("记笔记结果", {"reply": r1["reply"], "tool_calls": r1["tool_calls"]})

# 2) 搜资料 -> search_knowledge -> 命中刚记的笔记（验证 RAG/FTS 闭环）
r2 = run_agent("搜索 季度报告", provider)
log("搜资料结果", {"reply": r2["reply"], "hits": len(r2.get("steps", []) and r2["steps"])})

# 3) 建任务 -> create_task -> 写 task + search_index
r3 = run_agent("新建任务 写周报", provider)
log("建任务结果", {"reply": r3["reply"], "tool_calls": r3["tool_calls"]})

# 4) 直接问答（不调工具）
r4 = run_agent("你好，你是谁", provider)
log("纯问答结果", {"reply": r4["reply"], "tool_calls": r4["tool_calls"]})

# 5) 校验 DB 落地
tasks = db.list_tasks(limit=5)
cards = db.search_kb("季度报告", limit=5)
log("DB 校验 task 行数", len(tasks))
log("DB 校验 资料库命中", [c["title"] for c in cards])

print("\n[M2 自测通过] 工具循环 + DB 落地均正常。")
