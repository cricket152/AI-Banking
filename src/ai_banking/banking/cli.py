"""显式、先备份、只增表的本地数据库升级。"""

import argparse
import sqlite3
from contextlib import closing
from uuid import uuid4

from ai_banking.banking.schema import create_schema, ready
from ai_banking.config import Settings
from ai_banking.store import Store


def upgrade(store):
    if not store.path.is_file():
        raise ValueError("数据库不存在；请先启动应用或创建本地用户")
    with store.transaction() as db:
        if ready(db):
            return None
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("数据库完整性检查失败，停止升级")
    backup = store.path.with_name(store.path.stem + ".before-bank-" + uuid4().hex + ".sqlite3")
    with closing(sqlite3.connect(store.path)) as source, closing(sqlite3.connect(backup)) as target:
        source.backup(target)
    with store.transaction() as db:
        create_schema(db, store.clock())
        if db.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError("数据库引用检查失败，升级已回滚；备份已保留")
    return backup


def main():
    parser = argparse.ArgumentParser(description="升级本地模拟银行数据库（只增表，先完整备份）")
    parser.add_argument("command", choices=["upgrade"])
    parser.add_argument("--yes", action="store_true", help="明确同意本次增表升级")
    args = parser.parse_args()
    settings = Settings.from_env()
    store = Store(settings.database)
    print(f"目标数据库：{store.path.resolve()}")
    print("添加操作、账本、授权、任务、审计与虚构订阅等9张表；保留现有用户、密码、余额和流水。")
    if not args.yes and input("已了解影响并同意升级？输入 yes：").strip() != "yes":
        parser.exit(0, "未执行升级。\n")
    try:
        backup = upgrade(store)
    except (ValueError, sqlite3.Error) as error:
        parser.exit(1, f"升级失败：{type(error).__name__}；未自动恢复或删除任何文件。\n")
    print(f"升级完成。备份：{backup}" if backup else "银行表已经就绪，无需升级。")


if __name__ == "__main__":
    main()
