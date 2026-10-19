"""LLM 提供者抽象层。

为什么要有这一层（思考逻辑）：
- 平台定位是“可插拔多模型”：豆包默认，预留通义/GLM/本地 Ollama。
- 业务代码（工具循环、命令面板、分析引擎）只依赖 LLMProvider 这个抽象，
  不关心背后是谁在回答。换模型=改配置，不改动业务。
- 同时，本地/沙箱里往往没有 API key，为了“没有钥匙也能跑通整条智能体链路”，
  内置一个 MockProvider，用于联调和自动化测试。

统一契约：
- chat(messages, tools=None, tool_choice="auto") -> ChatMessage
- messages 是 OpenAI 风格字典列表（role/content/tool_calls/tool_call_id），
  这样豆包（走 OpenAI 兼容协议）可以原样透传，零转换成本。
- ChatMessage 只暴露业务关心的两个字段：content（文本）和 tool_calls（工具调用）。
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .. import config


@dataclass
class ToolCall:
    """一次工具调用。arguments 已经是解析后的 dict，便于 dispatch 直接展开。"""
    id: str
    name: str
    arguments: Dict


@dataclass
class ChatMessage:
    """统一的模型返回，解耦于具体 SDK 的响应对象。"""
    role: str
    content: Optional[str] = None
    tool_calls: List[ToolCall] = field(default_factory=list)
    tool_call_id: Optional[str] = None
    name: Optional[str] = None


class LLMProvider(ABC):
    """所有模型适配器的统一接口。"""

    @abstractmethod
    def chat(
        self,
        messages: List[Dict],
        tools: Optional[List[Dict]] = None,
        tool_choice: str = "auto",
    ) -> ChatMessage:
        ...

    @property
    def name(self) -> str:
        return self.__class__.__name__


class MockProvider(LLMProvider):
    """离线 Provider：没有 API key 时也能跑通工具循环，便于联调与测试。

    实现逻辑（启发式，不调用真实模型）：
    - 看最后一条消息：如果是 tool 结果，就基于结果生成一句中文总结（收尾）；
    - 否则根据用户输入的关键词决定调哪个工具，或给一个纯文本回答。
    它存在的唯一目的，是让“工具循环 / dispatch / DB 落地”这条链路在没有网络、
    没有密钥时也能被验证——这是 MockProvider 和真实 provider 的边界。
    """

    def chat(self, messages, tools=None, tool_choice="auto") -> ChatMessage:
        last = messages[-1] if messages else {"role": "user", "content": ""}

        # 第二轮及以后：已经执行过工具，该收尾总结了
        if last.get("role") == "tool":
            return self._summarize_tool(last)

        text = (last.get("content") or "").strip()

        # 意图 1：记住 / 存笔记 -> remember（去掉命令前缀，存干净内容）
        if any(k in text for k in ("记住", "记一下", "存一下", "记笔记", "存笔记")):
            return ChatMessage(
                role="assistant",
                tool_calls=[ToolCall(
                    id="call_remember",
                    name="remember",
                    arguments={"content": self._strip_prefix(text)},
                )],
            )

        # 意图 2：搜索 / 查资料 -> search_knowledge（只取关键词，去掉“搜索”等触发词）
        if any(k in text for k in ("搜索", "查一下", "查资料", "知识库", "搜 ")):
            q = self._extract_after(text, ("搜索", "查一下", "查资料", "知识库", "搜"))
            return ChatMessage(
                role="assistant",
                tool_calls=[ToolCall(
                    id="call_search",
                    name="search_knowledge",
                    arguments={"query": q or text},
                )],
            )

        # 意图 3：新建任务 -> create_task
        if "任务" in text and any(v in text for v in ("建", "新建", "创建", "加", "添加", "加个")):
            title = self._extract_after(text, ("任务", "建", "新建", "创建", "添加"))
            return ChatMessage(
                role="assistant",
                tool_calls=[ToolCall(
                    id="call_task",
                    name="create_task",
                    arguments={"title": title or text},
                )],
            )

        # 兜底：纯文本回答（不调工具）
        return ChatMessage(
            role="assistant",
            content=f"[离线模拟回答] 我已收到你的消息：“{text}”。"
                    f"（当前为 MockProvider，未接入真实模型。配置 ARK_API_KEY 后即走豆包。）",
        )

    def _extract_after(self, text: str, markers) -> str:
        for m in markers:
            idx = text.find(m)
            if idx != -1:
                rest = text[idx + len(m):].strip(" ：:，。、")
                if rest:
                    return rest
        return text

    def _strip_prefix(self, text: str) -> str:
        """去掉“记一下/记住/存一下/记笔记：”等命令前缀，存干净内容。"""
        prefixes = ("记一下", "记住", "存一下", "记笔记", "存笔记", "记：", "存：")
        for p in prefixes:
            if text.startswith(p):
                return text[len(p):].strip(" ：:，。")
        return text.strip()

    def _summarize_tool(self, tool_msg: Dict) -> ChatMessage:
        try:
            data = json.loads(tool_msg.get("content") or "{}")
        except json.JSONDecodeError:
            data = {}
        name = tool_msg.get("name", "工具")
        if name == "remember":
            return ChatMessage(role="assistant",
                               content=f"已帮你记下：「{data.get('content', '')}」（条目 #{data.get('id')}）。")
        if name == "create_task":
            return ChatMessage(role="assistant",
                               content=f"已新建任务「{data.get('title', '')}」（#{data.get('id')}），可在任务列表查看。")
        if name == "search_knowledge":
            hits = data.get("results", [])
            if not hits:
                return ChatMessage(role="assistant", content="没在资料库里找到相关内容。")
            lines = "\n".join(f"- {h.get('title', '')}：{h.get('content', '')[:60]}" for h in hits)
            return ChatMessage(role="assistant", content=f"在资料库找到 {len(hits)} 条：\n{lines}")
        return ChatMessage(role="assistant", content="已执行完毕。")


def get_provider() -> LLMProvider:
    """工厂：按配置返回 provider。

    逻辑：
    - 配置了 ARK_API_KEY 且 AI_PROVIDER=doubao -> 真实豆包；
    - 否则 -> MockProvider（保证本地零配置可跑）。
    这样“先跑通链路、再接真实模型”的节奏不被密钥卡住。
    """
    provider_kind = (config.AI_PROVIDER or "doubao").lower()
    if provider_kind == "doubao" and config.ARK_API_KEY:
        # 延迟导入，避免没装 openai 时整个模块 import 失败
        from .doubao import DoubaoProvider
        return DoubaoProvider(
            api_key=config.ARK_API_KEY,
            base_url=config.ARK_BASE_URL,
            model=config.ARK_MODEL,
        )
    return MockProvider()
