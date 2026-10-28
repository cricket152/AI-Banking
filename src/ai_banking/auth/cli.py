"""本机用户管理；密码仅通过 getpass 输入。"""

import argparse
import getpass

from ai_banking.auth import Auth
from ai_banking.config import Settings
from ai_banking.store import Store


def main():
    parser = argparse.ArgumentParser(description="管理本地模拟用户和账户")
    parser.add_argument("command", choices=["create-user", "reset-password", "disable-user"])
    parser.add_argument("username")
    args = parser.parse_args()
    settings = Settings.from_env()
    store = Store(settings.database)
    store.initialize()
    auth = Auth(store, settings)
    try:
        if args.command == "disable-user":
            auth.change_user(args.username)
        else:
            password = getpass.getpass("密码（1–128 个字符）：")
            if password != getpass.getpass("再次输入密码："):
                raise ValueError("两次密码不一致")
            if args.command == "create-user":
                auth.create_user(args.username, password)
            else:
                auth.change_user(args.username, password)
    except (ValueError, EOFError) as error:
        parser.exit(1, f"操作失败：{error}\n")
    print("操作完成。创建用户时已初始化独立的虚构账户与流水。")


if __name__ == "__main__":
    main()
