"""Skills 加载器 — 扫描 skills/ 目录，解析 SKILL.md，提供渐进式披露

遵循 agentskills.io 标准：
- Level 1: 启动时提取 name + description 注入 system prompt（~100 tokens/skill）
- Level 2: LLM 通过 load_skill 工具自主拉取完整 SKILL.md
- Level 3: SKILL.md 中引用的额外文件按需加载
"""

import json
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
        self._all_metas: Optional[list[SkillMeta]] = None  # 全量元数据缓存（含已禁用）
        self._content_cache: dict[str, str] = {}            # Level 2/3 内容缓存
        self._disabled: Optional[set[str]] = None            # 禁用列表缓存

    @property
    def skills_dir(self) -> str:
        """返回技能目录的绝对路径"""
        if os.path.isabs(self._skills_dir):
            return self._skills_dir
        # 相对路径 → 从项目根目录计算
        return str(Path(__file__).resolve().parent.parent.parent / self._skills_dir)

    @property
    def config_path(self) -> str:
        """技能配置文件的路径"""
        return os.path.join(self.skills_dir, "skills_config.json")

    # ---- 配置读写 ----

    def _load_config(self) -> dict:
        """读取技能配置文件"""
        path = self.config_path
        if not os.path.isfile(path):
            return {"disabled": []}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"技能配置文件读取失败: {e}")
            return {"disabled": []}

    def _save_config(self, config: dict):
        """保存技能配置文件"""
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

    def _get_disabled(self) -> set[str]:
        """获取禁用技能集合（带缓存）"""
        if self._disabled is None:
            config = self._load_config()
            self._disabled = set(config.get("disabled", []))
        return self._disabled

    def _invalidate_metas(self):
        """清空元数据缓存（配置变更后调用）"""
        with self._lock:
            self._all_metas = None

    # ---- 启用/禁用 API ----

    def is_disabled(self, name: str) -> bool:
        """检查技能是否被禁用"""
        return name in self._get_disabled()

    def disable_skill(self, name: str) -> bool:
        """禁用一个技能，返回是否成功（已禁用返回 False）"""
        disabled = self._get_disabled()
        if name in disabled:
            return False
        disabled.add(name)
        config = self._load_config()
        config["disabled"] = sorted(disabled)
        self._save_config(config)
        self._invalidate_metas()
        logger.info(f"技能已禁用: {name}")
        return True

    def enable_skill(self, name: str) -> bool:
        """启用一个技能，返回是否成功（未被禁用返回 False）"""
        disabled = self._get_disabled()
        if name not in disabled:
            return False
        disabled.discard(name)
        config = self._load_config()
        config["disabled"] = sorted(disabled)
        self._save_config(config)
        self._disabled = disabled  # 更新缓存
        self._invalidate_metas()
        logger.info(f"技能已启用: {name}")
        return True

    # ---- 扫描与加载 ----

    def _scan_all(self) -> list[SkillMeta]:
        """扫描 skills 目录，返回所有技能元数据（含已禁用），带缓存"""
        with self._lock:
            if self._all_metas is not None:
                return self._all_metas

            dir_path = self.skills_dir
            if not os.path.isdir(dir_path):
                logger.warning(f"Skills 目录不存在: {dir_path}")
                self._all_metas = []
                return self._all_metas

            metas = []
            for entry in sorted(os.scandir(dir_path), key=lambda e: e.name):
                if not entry.is_dir():
                    continue
                skill_md = _find_skill_md(entry.path)
                if not skill_md:
                    continue
                meta = _parse_frontmatter(skill_md)
                if meta is None:
                    continue
                meta.dir_path = entry.path
                metas.append(meta)

            self._all_metas = metas
            logger.info(f"技能扫描完成：在 {dir_path} 共发现 {len(metas)} 个技能")
            return self._all_metas

    def discover(self) -> list[SkillMeta]:
        """返回所有已启用的技能元数据（Level 1），共享 _scan_all 缓存"""
        all_metas = self._scan_all()
        disabled = self._get_disabled()
        return [m for m in all_metas if m.name not in disabled]

    def list_all_skills(self) -> list[dict]:
        """列出所有技能（含已禁用），共享 _scan_all 缓存"""
        all_metas = self._scan_all()
        disabled = self._get_disabled()
        return [{
            "name": m.name,
            "description": m.description,
            "version": m.version,
            "tags": m.tags,
            "disabled": m.name in disabled,
        } for m in all_metas]

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

        file_path = _find_skill_md(os.path.join(self.skills_dir, name))
        if not file_path:
            logger.warning(f"技能文件不存在: skills/{name}/{{SKILL.md,skill.md}}")
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

    def load_skill_resource(self, name: str, resource_path: str) -> Optional[str]:
        """加载 skill 内的附属文件（Level 3），带路径越界保护

        Args:
            name: 技能名称
            resource_path: 资源路径，相对于 skills/<name>/ 目录

        Returns:
            文件内容，或 None
        """
        skill_dir = os.path.join(self.skills_dir, name)
        if not os.path.isdir(skill_dir):
            return None

        target = os.path.normpath(os.path.join(skill_dir, resource_path))
        # 防止 .. 逃逸到 skill 目录外
        if not target.startswith(os.path.normpath(skill_dir) + os.sep):
            logger.warning(f"路径越界: {resource_path}")
            return None
        if not os.path.isfile(target):
            return None

        try:
            with open(target, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            logger.error(f"读取资源文件失败: {target}, 错误: {e}")
            return None

    def list_skill_dir(self, name: str) -> list[str]:
        """递归列出 skill 目录下所有文件（相对路径），排除 SKILL.md

        Args:
            name: 技能名称

        Returns:
            文件路径列表（相对于 skills/<name>/），按路径排序
        """
        skill_dir = os.path.join(self.skills_dir, name)
        if not os.path.isdir(skill_dir):
            return []

        files = []
        for root, _, filenames in os.walk(skill_dir):
            for fn in filenames:
                if fn.lower() == "skill.md":
                    continue
                full = os.path.join(root, fn)
                rel = os.path.relpath(full, skill_dir)
                files.append(rel)
        return sorted(files)


def _find_skill_md(dir_path: str) -> Optional[str]:
    """在给定目录下查找 SKILL.md（优先大写，兜底小写）"""
    for fname in ("SKILL.md", "skill.md"):
        path = os.path.join(dir_path, fname)
        if os.path.isfile(path):
            return path
    return None


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
