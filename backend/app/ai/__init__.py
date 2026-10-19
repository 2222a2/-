"""M2 AI 助手层包。

导入本包即完成“工具注册”（见 tools 模块的模块级注册），
后续 main 挂载 router 后即可对外提供 /api/ai/* 能力。
"""
from .provider import LLMProvider, ChatMessage, MockProvider, get_provider
from .tools import ToolRegistry, registry
from .agent import run_agent
from .rag import Retriever, get_retriever

# 触发基础工具注册（create_task / list_tasks / search_knowledge / remember）
from . import tools  # noqa: F401,E402
from . import router  # noqa: F401,E402

__all__ = [
    "LLMProvider", "ChatMessage", "MockProvider", "get_provider",
    "ToolRegistry", "registry", "run_agent", "Retriever", "get_retriever",
]
