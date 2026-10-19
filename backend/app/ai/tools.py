"""工具注册表 + 基础工具。

M2 的“工具”是什么（作用）：
- 工具是 AI 能“真实动手做”的能力，把自然语言意图翻译成后端动作
  （建任务、查资料、记笔记…）。其他模块（M3 任务、M4 分析、M1 文档）都通过
  “往这个注册表加工具”来让 AI 拥有新能力——这是 M2 被依赖的核心原因：
  上层模块不需要自己写 AI 调用，只注册工具即可被智能体调度。
- 每个工具 = 一份 JSON Schema 声明（给模型看）+ 一个真实执行函数（给后端跑）。
- ToolRegistry 负责：① 收集所有 schema 喂给模型；② 维护 name->函数 的 dispatch 映射。

设计要点：
- 用装饰器 @tool(...) 注册，写工具和声明在同一处，避免两处不同步；
- dispatch 真实执行，异常被包成 {error:...} 回灌模型，而不是让整轮崩掉；
- 敏感动作（删除/外部发送）这里先不暴露，等需要时加人工确认门槛。
"""
from __future__ import annotations

import functools
import json
from typing import Callable, Dict, List

from .. import db


class ToolRegistry:
    def __init__(self) -> None:
        self._schemas: List[Dict] = []
        self._dispatch: Dict[str, Callable] = {}

    def tool(self, name: str, description: str, parameters: Dict) -> Callable:
        """装饰器：把函数注册成工具，同时登记它的 schema。"""
        def decorator(fn: Callable) -> Callable:
            schema = {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": parameters,
                },
            }
            self._schemas.append(schema)
            self._dispatch[name] = fn
            functools.update_wrapper(fn, fn)
            return fn
        return decorator

    def schemas(self) -> List[Dict]:
        """交给模型的工具声明列表。"""
        return self._schemas

    def dispatch(self, name: str, **kwargs) -> Dict:
        """执行一个工具，返回可被模型消费的 JSON 结果。

        逻辑：真实执行；异常转成结构化错误回灌模型，让模型自己决定怎么跟用户解释，
        而不是让整条智能体链路因为一个工具失败而中断。
        """
        fn = self._dispatch.get(name)
        if fn is None:
            return {"error": f"未知工具：{name}"}
        try:
            result = fn(**kwargs)
            return result if isinstance(result, dict) else {"result": result}
        except Exception as exc:  # noqa: BLE001 - 工具失败不应中断整轮
            return {"error": str(exc)}

    def names(self) -> List[str]:
        return list(self._dispatch.keys())


# 全局注册表：应用启动时构建一次，全程复用。
registry = ToolRegistry()


# ---------------------------------------------------------------------------
# 基础工具：这几个让智能体立刻具备“记得住 / 搜得到 / 建得了任务”的最小能力。
# M3/M4/M1 会在各自模块里继续往 registry 加工具。
# ---------------------------------------------------------------------------

@registry.tool(
    "create_task",
    "新建一个任务。可给定标题、截止时间、紧急度(0/1)、重要度(0/1)。",
    {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "任务标题"},
            "deadline": {"type": "string", "description": "截止时间 ISO 字符串，可选"},
            "urgency": {"type": "integer", "description": "紧急度 0 或 1"},
            "importance": {"type": "integer", "description": "重要度 0 或 1"},
        },
        "required": ["title"],
    },
)
def create_task(title: str, deadline: str = None, urgency: int = 0, importance: int = 0) -> Dict:
    tid = db.insert_task(
        title=title,
        description=None,
        deadline=deadline,
        urgency=int(urgency),
        importance=int(importance),
    )
    return {"id": tid, "title": title, "ok": True}


@registry.tool(
    "list_tasks",
    "列出当前任务（按创建时间倒序），可限定状态和数量。",
    {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "返回数量上限，默认 20"},
            "status": {"type": "string", "description": "过滤状态 todo/doing/done/blocked，可选"},
        },
        "required": [],
    },
)
def list_tasks(limit: int = 20, status: str = None) -> Dict:
    rows = db.list_tasks(limit=int(limit), status=status)
    return {"count": len(rows), "tasks": rows}


@registry.tool(
    "search_knowledge",
    "在个人资料库（剪藏/上传/笔记/任务文档）里做全文检索，返回相关条目。",
    {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "检索关键词"},
            "top_k": {"type": "integer", "description": "返回条数，默认 5"},
        },
        "required": ["query"],
    },
)
def search_knowledge(query: str, top_k: int = 5) -> Dict:
    hits = db.search_kb(query, limit=int(top_k))
    results = [
        {"source": h["source_type"], "title": h["title"], "content": h["body"]}
        for h in hits
    ]
    return {"query": query, "results": results}


@registry.tool(
    "remember",
    "把一段内容存进个人资料库（当作笔记），方便以后检索与 RAG 引用。",
    {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "要记住的内容"},
            "title": {"type": "string", "description": "标题，可选，默认取内容前 20 字"},
        },
        "required": ["content"],
    },
)
def remember(content: str, title: str = None) -> Dict:
    # 改为走 M0 统一入库流水线，保证笔记同样进 FTS + 向量，可被 RAG 引用
    from .. import knowledge
    t = title or content[:20]
    cid = knowledge.ingest_card(title=t, body=content, source_type="note")
    return {"id": cid, "content": content, "ok": True}
