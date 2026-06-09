"""测试 build_review_tree 的输出结构"""
import asyncio
import json

from src.db.init_db import init_db
from src.vfs.task_context import set_current_task_id, clean_current_task_id, init_vfs, clean_vfs
from src.vfs.review_manager import ReviewManager
from src.db.sqlite_pool import db_pool

TASK_ID = "d43a4891-824c-41e5-81f4-292f53c1d151"


def print_review_tree(items, indent=0):
    """递归打印审批树"""
    prefix = "  " * indent
    for item in items:
        marker = ""
        if item['op_type'] in ('MKDIR', 'DELETE_DIR', 'RENAME_DIR'):
            marker = "[目录]"
        copy_hint = f" <- {item['copy_source']}" if item.get('copy_source') else ""
        print(f"{prefix}{marker}{item['op_type']}: {item['source']}"
              f"{' -> ' + item['target'] if item.get('target') else ''}{copy_hint}")
        if 'children' in item:
            print_review_tree(item['children'], indent + 2)


async def main():
    await init_db()

    set_current_task_id(TASK_ID)
    await init_vfs(TASK_ID)

    try:
        result = await ReviewManager.build_review_tree(TASK_ID)
        if result is None:
            print("无待审批变更（可能记录已是 is_reviewed=1 状态）")
            print("\n--- 检查 diff_records 状态 ---")
            from src.vfs.diff_table import DiffTable
            async with db_pool.get_conn() as conn:
                cursor = await conn.execute(
                    "SELECT is_reviewed, COUNT(*) as cnt FROM diff_records WHERE task_id=? GROUP BY is_reviewed",
                    (TASK_ID,),
                )
                for row in await cursor.fetchall():
                    print(f"  is_reviewed={row['is_reviewed']}: {row['cnt']} 条")
        else:
            print(f"task_id: {result['task_id']}")
            print("审批树：")
            print_review_tree(result['items'])
            print()
            print("JSON 格式：")
            print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        await clean_vfs()
        clean_current_task_id()
        await db_pool.close_all()


if __name__ == '__main__':
    asyncio.run(main())
