"""本地启动入口；仅监听回环地址，单进程。"""

import argparse
from urllib.parse import urlsplit

import uvicorn

from ai_banking.app import create_app
from ai_banking.config import Settings
from ai_banking.tracing import configure_terminal


def main():
    parser = argparse.ArgumentParser(description="启动 AI-Banking 本地模拟环境")
    parser.parse_args()
    settings = Settings.from_env()
    configure_terminal()
    origin = urlsplit(settings.origin)
    if origin.scheme != "http" or origin.hostname not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("此入口仅支持显式开启的本地 HTTP；其他部署需独立配置 HTTPS")
    print(f"AI-Banking 本地模拟环境：{settings.origin} · 模式 {settings.agent_mode}")
    uvicorn.run(
        create_app(settings),
        host=origin.hostname,
        port=origin.port or 80,
        proxy_headers=False,
        access_log=False,
    )


if __name__ == "__main__":
    main()
