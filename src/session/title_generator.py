"""会话标题自动生成"""
from openai import AsyncOpenAI

from src.config import MODEL, DEEPSEEK_BASE_URL, DEEPSEEK_API_KEY

TITLE_PROMPT = """根据以下对话的第一轮内容，生成一个简短标题，标题语言与用户所用语言一致
直接输出标题，不要加引号、标点或任何解释。

用户：{user_msg}
助手：{assistant_msg}

标题："""


async def generate_title(user_message: str, assistant_message: str) -> str:
    """根据首轮对话生成会话标题"""
    user_msg = user_message[:200]
    assistant_msg = assistant_message[:300]

    client = AsyncOpenAI(base_url=DEEPSEEK_BASE_URL, api_key=DEEPSEEK_API_KEY)
    response = await client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": TITLE_PROMPT.format(
            user_msg=user_msg, assistant_msg=assistant_msg
        )}],
        temperature=0.5,
        max_tokens=32,
        extra_body={"thinking": {"type": "disabled"}},
    )
    content = response.choices[0].message.content
    title = content.strip() if content else ""
    # 兜底：模型仍返回空时，用用户消息前 20 字作为标题
    if not title:
        title = user_message.strip()[:20]
    return title
