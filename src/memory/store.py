"""ChromaDB 封装 — 记忆的向量存储与检索"""

import uuid
from datetime import datetime, timezone

import chromadb
from chromadb.utils import embedding_functions

from src.memory.models import MemoryItem
from src.utils.common import logger


class MemoryStore:
    """封装 ChromaDB collection，提供记忆的增删查操作。

    ChromaDB 自动处理向量化：add() 时对 documents 字段做 embedding，
    query() 时对 query_texts 做 embedding 并计算余弦相似度。
    """

    def __init__(self, persist_dir: str):
        self.client = chromadb.PersistentClient(path=persist_dir)
        self.collection = self.client.get_or_create_collection(
            name="memories",
            embedding_function=embedding_functions.DefaultEmbeddingFunction(),
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(f"MemoryStore 初始化完成，当前记忆数: {self.collection.count()}")

    def add(self, items: list[MemoryItem], session_id: str) -> int:
        """批量添加记忆。

        preference 类型按 key 做 upsert（同 key 删旧插新）。
        fact/identity 类型始终追加。

        Returns:
            实际新增的记忆数
        """
        if not items:
            return 0

        ids: list[str] = []
        documents: list[str] = []
        metadatas: list[dict] = []
        now = datetime.now(timezone.utc).isoformat()

        for item in items:
            # preference 类型做 upsert：先删旧，再插新
            if item.memory_type == "preference" and item.key:
                self._delete_by_key(item.key)

            doc_id = str(uuid.uuid4())
            ids.append(doc_id)
            documents.append(item.value)
            metadatas.append({
                "memory_type": item.memory_type,
                "key": item.key,
                "session_id": session_id,
                "created_at": now,
            })

        self.collection.add(ids=ids, documents=documents, metadatas=metadatas)
        logger.debug(f"MemoryStore: 添加 {len(ids)} 条记忆 (session={session_id[:8]}...)")
        return len(ids)

    def query(self, text: str, n_results: int = 5) -> list[dict]:
        """语义搜索相关记忆（facts + identity）。

        Args:
            text: 搜索文本（通常是用户 query）
            n_results: 返回结果数

        Returns:
            [{"id": ..., "value": ..., "memory_type": ..., "key": ..., "distance": ...}, ...]
        """
        if not text or not text.strip():
            return []

        try:
            results = self.collection.query(
                query_texts=[text],
                n_results=min(n_results, self.collection.count()),
                where={"$or": [
                    {"memory_type": "fact"},
                    {"memory_type": "identity"},
                ]},
                include=["documents", "metadatas", "distances"],
            )
        except Exception:
            # collection 为空或 where 过滤后无结果时 ChromaDB 可能抛异常
            return []

        if not results["ids"] or not results["ids"][0]:
            return []

        output = []
        for i, doc_id in enumerate(results["ids"][0]):
            output.append({
                "id": doc_id,
                "value": results["documents"][0][i],
                "memory_type": results["metadatas"][0][i].get("memory_type", ""),
                "key": results["metadatas"][0][i].get("key", ""),
                "distance": results["distances"][0][i] if results["distances"] else None,
            })
        return output

    def get_preferences(self) -> list[dict]:
        """获取全部 preference 类型记忆"""
        try:
            results = self.collection.get(
                where={"memory_type": "preference"},
                include=["documents", "metadatas"],
            )
        except Exception:
            return []

        if not results["ids"]:
            return []

        output = []
        for i, doc_id in enumerate(results["ids"]):
            output.append({
                "id": doc_id,
                "value": results["documents"][i],
                "key": results["metadatas"][i].get("key", ""),
            })
        return output

    def delete(self, memory_id: str) -> bool:
        """删除单条记忆"""
        try:
            self.collection.delete(ids=[memory_id])
            return True
        except Exception:
            return False

    def count(self) -> int:
        """记忆总数"""
        return self.collection.count()

    # ---- 内部方法 ----

    def _delete_by_key(self, key: str) -> None:
        """删除指定 key 的 preference 记忆（用于 upsert）"""
        try:
            existing = self.collection.get(
                where={"$and": [
                    {"memory_type": "preference"},
                    {"key": key},
                ]},
            )
            if existing and existing["ids"]:
                self.collection.delete(ids=existing["ids"])
        except Exception:
            pass  # 没有旧记录或 collection 为空，忽略
