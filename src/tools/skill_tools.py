"""技能工具 — LLM 可自主调用以获取技能完整内容

核心工具：
- load_skill: 加载指定技能的完整 SKILL.md + 资源清单（Level 2）
             传 resource 参数可读取附属文件（Level 3）
- list_skills: 列出所有可用技能的名称和描述
"""

from typing import Optional

from pydantic import BaseModel, Field

from src.skills.loader import get_loader
from src.tools.registry import registry


class LoadSkillInput(BaseModel):
    name: str = Field(description="技能名称，如 file-organize。可用 list_skills 查看所有技能名称")
    resource: Optional[str] = Field(
        default=None,
        description="附属资源路径。不传则返回 SKILL.md 正文 + 附属资源文件列表",
    )


def load_skill(name: str, resource: Optional[str] = None) -> str:
    """加载指定技能的内容

    - resource=None: 返回 SKILL.md 正文，末尾附上资源文件列表
    - resource="references/xxx.md": 返回该资源文件内容
    """
    loader = get_loader()

    # Level 3：读取指定资源
    if resource:
        content = loader.load_skill_resource(name, resource)
        if content is None:
            return f"资源不存在: {name}/{resource}"
        return content

    # Level 2：返回 SKILL.md + 资源列表
    content = loader.load_skill(name)
    if content is None:
        # 列出可用技能帮助 LLM 修正
        metas = loader.discover()
        available = ", ".join(m.name for m in metas)
        return f"技能 '{name}' 不存在。可用技能: {available}"

    # 末尾附上资源文件列表
    files = loader.list_skill_dir(name)
    if files:
        content += "\n\n---\n## 附属资源\n"
        for f in files:
            content += f"- {f}\n"

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
    description=(
        "加载指定技能的完整指令。当判断当前任务需要某个技能时调用此工具。可传 resource 参数读取技能附属资源文件。"
    ),
    handler=load_skill,
    args_schema=LoadSkillInput,
)

registry.register(
    name="list_skills",
    description="列出所有可用技能的名称和描述，用于了解当前可用的技能能力",
    handler=list_skills,
    args_schema=ListSkillsInput,
)
