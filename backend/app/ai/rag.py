"""RAG 检索层。

RAG 在平台里的角色（作用）：
- 用户问“之前那个方案怎么写的”时，AI 不该凭记忆瞎编，而应先从个人资料库
  把相关片段捞出来，拼进上下文再回答——这就是“不用找资料”的底层。
- 检索分两路：① 关键词（FTS5 trigram，开箱即用，中文子串即可命中）；
  ② 语义（chromadb 向量，能懂同义/近义，需装 chromadb +  embedding 模型）。

设计：抽象 Retriever 统一接口，FTS 实现默认生效，chromadb 实现按需启用。
这样 M2 现在就能跑（不依赖重依赖），语义检索作为可升级路径随时接上。

M0 补充（为什么加写入端）：
- 之前 ChromaRetriever 只有 retrieve()（查询侧），缺少“资料入库时把向量写进来”的一侧，
  导致 RAG_BACKEND=chromadb 时只能查、不能存，语义检索是空的。
- 现在用 index_into_chroma() 统一承担“卡片 → 向量 → chromadb”的写入，
  由入库流水线在每次 ingest_card() 时调用；没装 chromadb 时静默跳过，FTS 兜底，平台照常工作。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from .. import config, db


# ---------------------------------------------------------------------------
# chromadb 写入端（M0 新增）
# ---------------------------------------------------------------------------
# 缓存 PersistentClient / Collection，避免每条资料都重连。
_chroma_client = None
_chroma_col = None
_CHROMA_NAME = "worklearn_kb"


def index_into_chroma(doc_id: int, text: str, metadata: Optional[Dict] = None) -> bool:
    """把一条资料（卡片）写进 chromadb 向量库。仅当 RAG_BACKEND=chromadb 且能导入时执行。

    逻辑：
    - 外层用 config.RAG_BACKEND 门控，默认 fts 时不碰 chromadb，零开销；
    - 导入 / 建库 / 模型加载任何一步失败都静默返回 False，不影响主流程（FTS 仍可用）；
    - upsert 用 str(doc_id) 作主键，删除/更新时同键覆盖，天然幂等。
    返回 True 表示成功写入向量，False 表示未写入（走 FTS 兜底）。
    """
    if (config.RAG_BACKEND or "fts").lower() != "chromadb":
        return False
    global _chroma_client, _chroma_col
    try:
        import chromadb  # 延迟导入：未安装不影响其它路径
        if _chroma_client is None:
            _chroma_client = chromadb.PersistentClient(path=str(config.DATA_DIR / "chroma"))
            _chroma_col = _chroma_client.get_or_create_collection(_CHROMA_NAME)
        _chroma_col.upsert(
            ids=[str(doc_id)],
            documents=[text],
            metadatas=[metadata or {}],
        )
        return True
    except Exception:
        # 任何失败（没装 chromadb / 模型下载失败 / 磁盘问题）都降级到 FTS，不让入库失败
        _chroma_client = None
        _chroma_col = None
        return False


def remove_from_chroma(doc_id: int) -> None:
    """从 chromadb 删除一条资料（删除卡片时清理向量，避免脏数据）。"""
    global _chroma_col
    if _chroma_col is None:
        return
    try:
        _chroma_col.delete(ids=[str(doc_id)])
    except Exception:
        pass


class Retriever(ABC):
    @abstractmethod
    def retrieve(self, query: str, top_k: int = 5) -> List[Dict]: ...


class SqliteFtsRetriever(Retriever):
    """基于 SQLite FTS5 的关键词检索，零额外依赖，立即可用。"""

    def retrieve(self, query: str, top_k: int = 5) -> List[Dict]:
        hits = db.search_kb(query, limit=top_k)
        return [
            {"title": h["title"], "content": h["body"], "source": h["source_type"]}
            for h in hits
        ]


class ChromaRetriever(Retriever):
    """基于 chromadb 的语义向量检索（需安装 chromadb 与 embedding 模型）。

    注意：向量库与 SQLite 的写入同步发生在“资料入库流水线”（M0 资料底座），
    这里只负责查询。M2 先把这个口子留好，M0 接 chromadb 时直接复用。
    """

    def __init__(self, collection_name: str = _CHROMA_NAME) -> None:
        import chromadb  # 延迟导入，未安装时不影响其它路径
        self._client = chromadb.PersistentClient(
            path=str(config.DATA_DIR / "chroma")
        )
        self._col = self._client.get_or_create_collection(collection_name)

    def retrieve(self, query: str, top_k: int = 5) -> List[Dict]:
        # embedding 由 chromadb 内置的 onnx 模型或外部传入；这里走 chromadb 默认。
        res = self._col.query(query_texts=[query], n_results=top_k)
        out: List[Dict] = []
        if res and res.get("documents") and res["documents"][0]:
            for doc, meta in zip(res["documents"][0], res["metadatas"][0] or []):
                out.append({
                    "title": (meta or {}).get("title", ""),
                    "content": doc,
                    "source": (meta or {}).get("source", ""),
                })
        return out

    def add(self, doc_id: int, text: str, metadata: Optional[Dict] = None) -> bool:
        """写入侧：把一条资料 upsert 进向量库（与 index_into_chroma 同集合，供 M0 直接调用）。"""
        try:
            self._col.upsert(
                ids=[str(doc_id)],
                documents=[text],
                metadatas=[metadata or {}],
            )
            return True
        except Exception:
            return False


def get_retriever() -> Retriever:
    """工厂：按 RAG_BACKEND 选择检索器。

    - chromadb：装了 chromadb 才用，否则自动回退 FTS（保证不崩）；
    - 其它/默认：FTS5 关键词检索。
    """
    backend = (config.RAG_BACKEND or "fts").lower()
    if backend == "chromadb":
        try:
            return ChromaRetriever()
        except Exception:
            # 没装 chromadb 或有问题 -> 回退关键词检索，不影响主流程
            return SqliteFtsRetriever()
    return SqliteFtsRetriever()
