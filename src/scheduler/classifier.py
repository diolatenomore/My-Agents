from src.models.task import TaskType
from src.utils.common import logger


class Classifier:

    @staticmethod
    async def classify(query:str):
        # MVP：用规则/关键词快速判断
        # 后续：可接入LLM做意图识别

        # 研究-写作关键词
        research_write_ops = ["写作", "撰写", "文章", "研究"]
        # # 文件操作关键词
        # file_ops = ["修改", "创建", "删除", "重构", "文件", "代码", "函数"]
        # # 复杂任务关键词
        # complex_ops = ["分析", "优化", "排查", "迁移", "架构"]

        if any(kw in query for kw in research_write_ops):
            logger.info(f"任务类型分类：{TaskType.RESEARCH_WRITE}")
            return TaskType.RESEARCH_WRITE

        # 默认简单聊天任务
        logger.info(f"任务类型分类：{TaskType.CHAT}")
        return TaskType.CHAT

    def _infer_task_type(self, input: str) -> str:
        if "修改" in input or "重构" in input:
            return "code_modify"
        if "创建" in input:
            return "code_create"
        return "general"