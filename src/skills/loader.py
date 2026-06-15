"""Skills 加载器 — 扫描 skills/ 目录，解析 SKILL.md，提供渐进式披露

遵循 agentskills.io 标准：
- Level 1: 启动时提取 name + description 注入 system prompt（~100 tokens/skill）
- Level 2: LLM 通过 load_skill 工具自主拉取完整 SKILL.md
- Level 3: SKILL.md 中引用的额外文件按需加载
"""

import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from src.utils.common import logger


@dataclass
class SkillMeta:
    """技能元数据（Level 1）"""
    name: str
    description: str
    version: str = "1.0.0"
    tags: list = field(default_factory=list)
    dir_path: str = ""  # skill 目录路径


class SkillLoader:
    """Skills 加载器，支持扫描、解析、缓存"""

    def __init__(self, skills_dir: str = "skills"):
        """
        Args:
            skills_dir: skills 根目录路径，支持相对路径（相对于项目根目录）
        """
        self._skills_dir = skills_dir
        self._lock = threading.RLock()
        self._metas: Optional[list[SkillMeta]] = None  # Level 1 缓存
        self._content_cache: dict[str, str] = {}        # Level 2/3 缓存

    @property
    def skills_dir(self) -> str:
        """返回技能目录的绝对路径"""
        if os.path.isabs(self._skills_dir):
            return self._skills_dir
        # 相对路径 → 从项目根目录计算
        return str(Path(__file__).resolve().parent.parent.parent / self._skills_dir)

    def discover(self) -> list[SkillMeta]:
        """扫描 skills 目录，返回所有技能的元数据（Level 1）

        Returns:
            SkillMeta 列表，按 name 排序
        """
        with self._lock:
            if self._metas is not None:
                return self._metas

            dir_path = self.skills_dir
            if not os.path.isdir(dir_path):
                logger.warning(f"Skills 目录不存在: {dir_path}")
                self._metas = []
                return self._metas

            metas = []
            for entry in sorted(os.scandir(dir_path), key=lambda e: e.name):
                if not entry.is_dir():
                    continue
                skill_md = os.path.join(entry.path, "SKILL.md")
                if not os.path.isfile(skill_md):
                    continue
                meta = self._parse_frontmatter(skill_md)
                if meta:
                    meta.dir_path = entry.path
                    metas.append(meta)

            self._metas = metas
            logger.info(f"技能扫描完成：在 {dir_path} 共发现 {len(metas)} 个技能")
            return self._metas

    def load_skill(self, name: str) -> Optional[str]:
        """加载完整 SKILL.md 内容（Level 2），内容级缓存

        Args:
            name: 技能名称

        Returns:
            完整的 SKILL.md 文本内容，或 None
        """
        with self._lock:
            if name in self._content_cache:
                return self._content_cache[name]

        file_path = os.path.join(self.skills_dir, name, "SKILL.md")
        if not os.path.isfile(file_path):
            logger.warning(f"技能文件不存在: {file_path}")
            return None

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            with self._lock:
                self._content_cache[name] = content
            logger.info(f"技能已加载: {name} ({len(content)} 字符)")
            return content
        except Exception as e:
            logger.error(f"读取技能文件失败: {file_path}, 错误: {e}")
            return None

    @staticmethod
    def _parse_frontmatter(file_path: str) -> Optional[SkillMeta]:
        """解析 SKILL.md 的 YAML frontmatter，提取元数据

        Args:
            file_path: SKILL.md 文件路径

        Returns:
            SkillMeta 或 None
        """
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            logger.error(f"读取技能文件失败: {file_path}, 错误: {e}")
            return None

        # 检查是否以 --- 开头
        if not content.startswith("---"):
            logger.warning(f"技能文件缺少 frontmatter: {file_path}")
            return None

        # 提取两个 --- 之间的 YAML
        _, rest = content.split("---", 1)
        if "---" not in rest:
            logger.warning(f"技能文件 frontmatter 格式不完整: {file_path}")
            return None
        frontmatter, _ = rest.split("---", 1)

        # 简易 YAML 解析（不引入 PyYAML 依赖，只解析必要字段）
        name = _extract_yaml_str(frontmatter, "name")
        description = _extract_yaml_value(frontmatter, "description")
        version = _extract_yaml_str(frontmatter, "version") or "1.0.0"
        tags = _extract_yaml_list(frontmatter, "tags")

        if not name or not description:
            logger.warning(f"技能文件缺少必填字段 name/description: {file_path}")
            return None

        return SkillMeta(
            name=name,
            description=description,
            version=version,
            tags=tags,
        )


# ============ YAML 解析辅助 ============

def _extract_yaml_str(yaml_str: str, key: str) -> Optional[str]:
    """从 YAML 字符串中提取单行字符串值"""
    for line in yaml_str.split("\n"):
        stripped = line.strip()
        if stripped.startswith(f"{key}:"):
            value = stripped[len(f"{key}:"):].strip()
            # 去掉引号
            value = value.strip('"').strip("'")
            return value if value else None
    return None


def _extract_yaml_value(yaml_str: str, key: str) -> Optional[str]:
    """从 YAML 字符串中提取值（支持多行 > 语法）"""
    lines = yaml_str.split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(f"{key}:"):
            value = stripped[len(f"{key}:"):].strip()
            if value == ">" or value == "|":
                # 多行值：收集后续缩进行
                parts = []
                for j in range(i + 1, len(lines)):
                    next_line = lines[j]
                    if not next_line or not next_line[0].isspace() and next_line.strip():
                        break
                    parts.append(next_line.strip())
                return " ".join(parts)
            else:
                value = value.strip('"').strip("'")
                return value if value else None
    return None


def _extract_yaml_list(yaml_str: str, key: str) -> list:
    """从 YAML 字符串中提取列表值（支持 [a, b, c] 格式）"""
    for line in yaml_str.split("\n"):
        stripped = line.strip()
        if stripped.startswith(f"{key}:"):
            value = stripped[len(f"{key}:"):].strip()
            if value.startswith("[") and value.endswith("]"):
                inner = value[1:-1]
                return [item.strip().strip('"').strip("'") for item in inner.split(",") if item.strip()]
            break
    return []


# ============ 模块级单例 + 便捷函数 ============

_loader: Optional[SkillLoader] = None
_loader_lock = threading.Lock()


def get_loader(skills_dir: str = "skills") -> SkillLoader:
    """获取 SkillLoader 单例，线程安全"""
    global _loader
    if _loader is not None:
        return _loader
    with _loader_lock:
        if _loader is None:
            _loader = SkillLoader(skills_dir)
        return _loader


def build_skills_catalog(skills_dir: str = "skills") -> str:
    """便捷函数：扫描技能目录，构建可注入 system prompt 的技能目录摘要

    Args:
        skills_dir: skills 根目录路径

    Returns:
        格式化的技能目录字符串，无技能时返回空字符串
    """
    loader = get_loader(skills_dir)
    metas = loader.discover()
    if not metas:
        return ""

    lines = ["## 可用技能"]
    lines.append("你可以通过调用 load_skill 工具来获取某个技能的完整指令。")
    lines.append("")
    for meta in metas:
        lines.append(f"- **{meta.name}**: {meta.description}")
    return "\n".join(lines)
