"""豆包（火山方舟 Volcengine Ark）适配器。

实现逻辑：
- 豆包原生走 OpenAI 兼容协议，只需要把 OpenAI SDK 的 base_url 指向 Ark 的地址，
  无需单独 SDK、无需改协议。这是选型上最省事、最稳的一条路。
- 模型可以是模型名（如 doubao-seed-1-6-250615）或 EndpointId（ep-xxxx），都填进 ARK_MODEL。
- 唯一改动点：把 SDK 返回对象翻译成我们统一契约 ChatMessage，
  OpenAI 的 tool_calls.arguments 是 JSON 字符串，这里解析成 dict 直接用。

敏感处理：api_key 只从环境变量读，绝不硬编码；缺 key 直接抛错，不静默降级到错误答案。
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional

from .provider import ChatMessage, LLMProvider, ToolCall


class DoubaoProvider(LLMProvider):
    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        if not api_key:
            raise ValueError("ARK_API_KEY 未配置，无法初始化豆包 Provider")
        # 延迟导入：没装 openai 时不至于让整个 ai 包 import 失败
        from openai import OpenAI
        self.client = OpenAI(base_url=base_url, api_key=api_key)
        self.model = model

    @property
    def name(self) -> str:
        return f"doubao:{self.model}"

    def chat(
        self,
        messages: List[Dict],
        tools: Optional[List[Dict]] = None,
        tool_choice: str = "auto",
    ) -> ChatMessage:
        params: Dict = {"model": self.model, "messages": messages}
        if tools:
            params["tools"] = tools
            params["tool_choice"] = tool_choice

        resp = self.client.chat.completions.create(**params)
        m = resp.choices[0].message

        tool_calls: List[ToolCall] = []
        if m.tool_calls:
            for tc in m.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))

        return ChatMessage(role="assistant", content=m.content, tool_calls=tool_calls)
