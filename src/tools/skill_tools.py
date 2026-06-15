"""技能工具 — LLM 可自主调用以获取技能完整内容

核心工具：
- load_skill: 加载指定技能的完整 SKILL.md（Level 2）
- list_skills: 列出所有可用技能的名称和描述
"""

from pydantic import BaseModel, Field

from src.skills.loader import get_loader
from src.tools.registry import registry


class LoadSkillInput(BaseModel):
    name: str = Field(description="技能名称，如 file-organize。可用 list_skills 查看所有技能名称")


def load_skill(name: str) -> str:
    """加载指定技能的完整 SKILL.md 内容"""
    loader = get_loader()
    content = loader.load_skill(name)
    if content is None:
        # 列出可用技能帮助 LLM 修正
        metas = loader.discover()
        available = ", ".join(m.name for m in metas)
        return f"技能 '{name}' 不存在。可用技能: {available}"
    return content


class ListSkillsInput(BaseModel):
    pass  # 无参数


def list_skills() -> str:
    """列出所有可用技能的名称和描述"""
    loader = get_loader()
    metas = loader.discover()
    if not metas:
        return "当前没有可用技能。"
    lines = ["# 可用技能"]
    for meta in metas:
        tags_str = ", ".join(meta.tags) if meta.tags else ""
        lines.append(f"- **{meta.name}** (v{meta.version}): {meta.description}")
        if tags_str:
            lines.append(f"  标签: {tags_str}")
    return "\n".join(lines)


# ============ 注册工具 ============

registry.register(
    name="load_skill",
    description="加载指定技能的完整指令。当判断当前任务需要某个技能时调用此工具。",
    handler=load_skill,
    args_schema=LoadSkillInput,
)

registry.register(
    name="list_skills",
    description="列出所有可用技能的名称和描述，用于了解当前可用的技能能力",
    handler=list_skills,
    args_schema=ListSkillsInput,
)
