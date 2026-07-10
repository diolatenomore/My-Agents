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

        所有类型统一用向量相似度去重：写入前先查询同类型已有记忆，
        若余弦距离 <= 阈值则跳过，避免重复写入。

        Returns:
            实际新增的记忆数
        """
        if not items:
            return 0

        from src.config import MEMORY_DEDUP_THRESHOLD

        ids: list[str] = []
        documents: list[str] = []
        metadatas: list[dict] = []
        now = datetime.now(timezone.utc).isoformat()

        for item in items:
            # 第二层防护：统一用相似度去重，对所有类型都做检查
            similar = self._find_similar(item.value, item.memory_type)
            if similar and similar["distance"] <= MEMORY_DEDUP_THRESHOLD:
                logger.debug(
                    f"跳过重复记忆 [{item.memory_type}]: {item.value[:50]}... "
                    f"(已有记忆距离={similar['distance']:.4f}: {similar['value'][:50]}...)"
                )
                continue

            doc_id = str(uuid.uuid4())
            ids.append(doc_id)
            documents.append(item.value)
            metadatas.append({
                "memory_type": item.memory_type,
                "key": item.key,
                "session_id": session_id,
                "created_at": now,
            })

        if not ids:
            return 0

        self.collection.add(ids=ids, documents=documents, metadatas=metadatas)
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

    def list_all(self, limit: int = 20, offset: int = 0,
                 memory_type: str | None = None) -> tuple[list[dict], int]:
        """分页列出记忆，按创建时间倒序。

        Args:
            limit: 每页条数
            offset: 偏移量
            memory_type: 可选类型过滤 (preference/fact/identity)

        Returns:
            (items, total_count)
        """
        where_filter = None
        if memory_type:
            where_filter = {"memory_type": memory_type}

        try:
            results = self.collection.get(
                where=where_filter,
                include=["documents", "metadatas"],
            )
        except Exception:
            return [], 0

        if not results["ids"]:
            return [], 0

        items = []
        for i, doc_id in enumerate(results["ids"]):
            meta = results["metadatas"][i]
            items.append({
                "id": doc_id,
                "value": results["documents"][i],
                "memory_type": meta.get("memory_type", ""),
                "key": meta.get("key", ""),
                "session_id": meta.get("session_id", ""),
                "created_at": meta.get("created_at", ""),
            })

        # 按创建时间倒序
        items.sort(key=lambda x: x["created_at"], reverse=True)
        total = len(items)
        items = items[offset:offset + limit]

        return items, total

    def update(self, memory_id: str, value: str, key: str = "") -> bool:
        """更新记忆内容和 key。

        ChromaDB 的 collection.update() 会对新 documents 重新 embedding。
        """
        try:
            existing = self.collection.get(
                ids=[memory_id],
                include=["metadatas"],
            )
        except Exception:
            return False

        if not existing["ids"]:
            return False

        old_meta = existing["metadatas"][0]
        new_meta = {
            "memory_type": old_meta.get("memory_type", ""),
            "key": key or old_meta.get("key", ""),
            "session_id": old_meta.get("session_id", ""),
            "created_at": old_meta.get("created_at", ""),
        }

        try:
            self.collection.update(
                ids=[memory_id],
                documents=[value],
                metadatas=[new_meta],
            )
            return True
        except Exception:
            return False

    def count(self) -> int:
        """记忆总数"""
        return self.collection.count()

    # ---- 内部方法 ----

    def _find_similar(self, text: str, memory_type: str) -> dict | None:
        """查询与给定文本最相似的同类型已有记忆。

        Returns:
            {"id": ..., "value": ..., "distance": ...} 或 None（无结果/异常）
        """
        try:
            results = self.collection.query(
                query_texts=[text],
                n_results=3,
                where={"memory_type": memory_type},
                include=["documents", "distances"],
            )
            if results["ids"] and results["ids"][0]:
                return {
                    "id": results["ids"][0][0],
                    "value": results["documents"][0][0],
                    "distance": results["distances"][0][0],
                }
        except Exception:
            pass
        return None


