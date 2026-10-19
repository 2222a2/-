"""智能体循环（Function Calling 工具循环）。

核心逻辑（实现）：模型返回 tool_calls -> 后端真实执行 -> 结果回灌模型 -> 继续推理，
直到模型不再调用工具，输出最终文本。

为什么必须这样：AI 本身不能“做事”，只能“决定做事”。工具循环就是把
“决定”翻译成“真实动作”再喂回“决定”的闭环，让模型能多步完成复杂任务
（例如：先搜索资料库 -> 再基于结果新建任务）。

关键安全/正确性约束：
1. MAX_ITER 上限：防止模型陷入无限工具调用（失控/烧钱/死循环）。
2. 必须保留带 tool_calls 的 assistant 消息：OpenAI 协议要求 tool 结果必须
   对应回哪次调用（靠 tool_call_id），缺了会直接报错。
3. 工具结果回灌后才能继续：模型要看到“刚才那步做成了什么”才能走下一步。
4. 每步记录 steps：把“模型决策 -> 工具执行 -> 结果”留痕，便于前端展示与复盘。
"""
from __future__ import annotations

import json
from typing import Callable, Dict, List, Optional

from .provider import ChatMessage, LLMProvider
from .tools import registry


# 系统提示词：给模型定角色 + 工具使用纪律。后续 M4 会用更严格的“状态机”约束。
SYSTEM_PROMPT = (
    "你是「工作学习一体化平台」的 AI 助手小渝。你的职责是帮用户管理任务、"
    "检索资料、记录笔记。当任务需要查资料或落库时，优先调用可用工具，"
    "不要凭空编造数据。回答简洁、直接、用中文。"
)


def run_agent(
    user_input: str,
    provider: LLMProvider,
    system_prompt: str = SYSTEM_PROMPT,
    max_iter: int = 8,
    tool_schemas: Optional[List[Dict]] = None,
    dispatch: Optional[Callable] = None,
    on_step=None,
) -> Dict:
    """跑一轮智能体对话。

    返回：{"reply": 最终文本, "steps": [决策/执行日志], "tool_calls": 次数}。
    on_step 可选回调，用于把每一步实时推给前端（流式/日志展示）。
    """
    tools = tool_schemas if tool_schemas is not None else registry.schemas()
    do = dispatch if dispatch is not None else registry.dispatch

    messages: List[Dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_input},
    ]
    steps: List[Dict] = []
    tool_call_count = 0

    for _ in range(max_iter):
        msg: ChatMessage = provider.chat(messages, tools=tools, tool_choice="auto")

        # 不再调用工具 -> 收尾，返回最终文本
        if not msg.tool_calls:
            reply = msg.content or ""
            steps.append({"type": "final", "content": reply})
            if on_step:
                on_step(steps[-1])
            return {"reply": reply, "steps": steps, "tool_calls": tool_call_count}

        # 保留带 tool_calls 的 assistant 消息（务必原样带上，供协议回查）
        assistant_msg = {
            "role": "assistant",
            "content": msg.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                    },
                }
                for tc in msg.tool_calls
            ],
        }
        messages.append(assistant_msg)
        steps.append({
            "type": "decision",
            "calls": [{"name": tc.name, "arguments": tc.arguments} for tc in msg.tool_calls],
        })
        if on_step:
            on_step(steps[-1])

        # 逐个执行工具，结果回灌
        for tc in msg.tool_calls:
            tool_call_count += 1
            result = do(tc.name, **tc.arguments)
            steps.append({"type": "action", "name": tc.name, "result": result})
            if on_step:
                on_step(steps[-1])
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "name": tc.name,
                "content": json.dumps(result, ensure_ascii=False),
            })

    return {
        "reply": "已达最大轮次，未收敛。",
        "steps": steps,
        "tool_calls": tool_call_count,
    }
