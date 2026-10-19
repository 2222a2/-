"""AI 层 HTTP 接口（挂在 /api/ai 下）。

提供 4 个入口，对应平台里 AI 的几种使用方式：
- GET  /api/ai/status   能力自检（哪个模型、RAG 后端、是否配了 key），前端状态灯用。
- POST /api/ai/chat     一次性问答（不带工具），适合随手问。
- POST /api/ai/agent    带工具的多轮智能体（记得住/搜得到/建任务），核心入口。
- POST /api/ai/command  命令面板入口：规则命中高频句式 -> 直接给动作；
                          否则交给 agent 走自然语言兜底。
"""
from __future__ import annotations

from fastapi import APIRouter

from .. import config
from ..schemas import (
    AiMessageIn, AiCommandIn, AiStatusOut, AgentOut, CommandOut,
)
from . import rag
from .agent import run_agent
from .provider import get_provider
from .tools import registry

router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.get("/status", response_model=AiStatusOut)
def ai_status():
    provider = get_provider()
    retriever = rag.get_retriever()
    return AiStatusOut(
        provider=provider.name,
        rag_backend=config.RAG_BACKEND,
        rag_retriever=retriever.__class__.__name__,
        api_key_configured=bool(config.ARK_API_KEY),
        tools=registry.names(),
    )


@router.post("/chat")
def chat(body: AiMessageIn):
    """一次性问答（不触发工具）。"""
    provider = get_provider()
    msg = provider.chat([{"role": "user", "content": body.message}])
    return {"reply": msg.content or ""}


@router.post("/agent", response_model=AgentOut)
def agent(body: AiMessageIn):
    """带工具的多轮智能体。"""
    provider = get_provider()
    return run_agent(body.message, provider)


@router.post("/command", response_model=CommandOut)
def command(body: AiCommandIn):
    """命令面板入口：规则 + AI 混合路由。"""
    import re
    text = body.text.strip()
    if not text:
        return CommandOut(action=None, params={}, preview="空命令")

    # 规则层：高频固定句式，快且可控。
    # 顺序很关键：建任务 → 记笔记 → 搜资料 → 生成报告（报告放搜索之后，
    # 否则“搜一下周报”会被“周报”规则误判成生成周报）。
    if m := re.match(r"^(新建任务|建任务|加任务)[：: ]?(.*)", text):
        title = m.group(2).strip() or text
        return CommandOut(action="create_task", params={"title": title},
                          preview=f"将新建任务：{title}")

    if any(k in text for k in ("记一下", "记笔记", "记 ")):
        # 记笔记：抽出要记的内容（去掉“记一下/记笔记/记 ”前缀）
        content = re.sub(r"^(记一下|记笔记|记)\s*", "", text).strip()
        return CommandOut(action="remember", params={"content": content},
                          preview=f"将记笔记：{content}")

    if any(k in text for k in ("搜索", "查资料", "搜一下", "搜 ", "查询")):
        # 搜资料：去掉搜索动词，剩下作为检索词
        q = re.sub(r"^(搜索|查资料|搜一下|查询)\s*", "", text)
        q = re.sub(r"^搜\s*", "", q).strip()
        return CommandOut(action="search_knowledge", params={"query": q},
                          preview=f"将检索资料库：{q}")

    # 生成真实 Office 文档（M1）：含“文档/word/excel/ppt/.docx…”等触发词即走文档生成。
    # 必须放在“周报”规则之前：否则“生成周报文档”会被误判成生成 Markdown 周报。
    if any(k in text for k in ("生成文档", "做文档", "出文档", "生成文件", "导出文档",
                                ".docx", ".xlsx", ".pptx", "word", "Word", "excel",
                                "Excel", "ppt", "PPT")) or "文档" in text:
        prompt = re.sub(r"^(生成文档|做文档|出文档|生成文件|导出文档|生成)\s*", "", text).strip()
        prompt = prompt.replace("文档", "").replace("Word", "").replace("word", "") \
                       .replace("Excel", "").replace("excel", "").replace("PPT", "") \
                       .replace("ppt", "").strip(" ：:，。、")
        if not prompt:
            prompt = text
        doc_type = ("excel" if any(k in text for k in ("excel", "Excel", "表格", ".xlsx", "xls"))
                    else "ppt" if any(k in text for k in ("ppt", "PPT", "演示", ".pptx"))
                    else "word")
        return CommandOut(action="gen_doc",
                          params={"prompt": prompt or text, "doc_type": doc_type},
                          preview=f"将生成{doc_type}文档：{prompt or text}")

    if "周报" in text or "月报" in text:
        rtype = "monthly" if "月" in text else "weekly"
        return CommandOut(action="gen_report", params={"type": rtype},
                          preview=f"将生成{'月' if rtype == 'monthly' else '周'}报")

    # 兜底：交给 agent（自然语言意图），让它决定调哪个工具
    provider = get_provider()
    result = run_agent(text, provider)
    return CommandOut(
        action="agent",
        params={},
        preview=result.get("reply", ""),
        steps=result.get("steps", []),
    )
