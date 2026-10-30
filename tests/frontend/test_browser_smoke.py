from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from fastapi import Response
from fastapi.responses import HTMLResponse

from ai_banking.app import create_app
from ai_banking.config import Settings

TEST_USERNAME = "browser_smoke"
TEST_PASSWORD = "browser-test-only-password"


def _find_browser() -> Path | None:
    configured = os.environ.get("AI_BANKING_BROWSER")
    if configured:
        resolved = shutil.which(configured)
        browser = Path(resolved or configured).expanduser()
        if not browser.is_file():
            pytest.fail(f"AI_BANKING_BROWSER 指向的 Chromium 浏览器不存在：{browser}")
        return browser

    for name in (
        "msedge",
        "msedge.exe",
        "chrome",
        "chrome.exe",
        "chromium",
        "chromium-browser",
        "google-chrome",
        "microsoft-edge",
    ):
        resolved = shutil.which(name)
        if resolved:
            return Path(resolved)

    if os.name == "nt":
        roots = {
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")),
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")),
            Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")),
        }
        for root in roots:
            for relative in (
                "Google/Chrome/Application/chrome.exe",
                "Microsoft/Edge/Application/msedge.exe",
            ):
                browser = root / relative
                if browser.is_file():
                    return browser
    elif sys.platform == "darwin":
        for browser in (
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
        ):
            if browser.is_file():
                return browser

    return None


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _add_browser_scenario(app) -> list[str]:
    scenario = Path(__file__).with_name("browser_scenario.js").read_text(encoding="utf-8")
    requests = []

    def serve_scenario():
        return Response(
            scenario,
            media_type="application/javascript",
            headers={"Cache-Control": "no-store"},
        )

    app.add_api_route(
        "/__frontend_test__/scenario.js",
        serve_scenario,
        methods=["GET"],
        include_in_schema=False,
    )

    @app.middleware("http")
    async def inject_browser_scenario(request, call_next):
        response = await call_next(request)
        requests.append(f"{request.method} {request.url.path} -> {response.status_code}")
        if request.method != "GET" or request.url.path != "/":
            return response

        body = b"".join([chunk async for chunk in response.body_iterator]).decode("utf-8")
        marker = "</body>"
        script = '<script src="/__frontend_test__/scenario.js" defer></script>'
        if marker not in body:
            raise RuntimeError("无法在首页注入测试专用脚本")
        body = body.replace(marker, f"{script}{marker}", 1)
        headers = dict(response.headers)
        for name in ("content-length", "content-type", "etag", "last-modified"):
            headers.pop(name, None)
        return HTMLResponse(body, status_code=response.status_code, headers=headers)

    return requests


@pytest.fixture
def browser_app(tmp_path):
    browser = _find_browser()
    if browser is None:
        pytest.skip(
            "未找到 Chromium 浏览器；可安装本机 Edge/Chrome/Chromium，或设置 AI_BANKING_BROWSER。"
        )

    port = _free_port()
    origin = f"http://127.0.0.1:{port}"
    app = create_app(
        Settings(database=tmp_path / "frontend-smoke.sqlite3", origin=origin, local_http=True)
    )
    app.state.store.initialize()
    app.state.auth.create_user(TEST_USERNAME, TEST_PASSWORD)
    requests = _add_browser_scenario(app)

    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="error",
            access_log=False,
        )
    )
    thread = threading.Thread(target=server.run, name="frontend-smoke-app", daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started:
            if not thread.is_alive():
                pytest.fail("前端冒烟测试用 FastAPI 服务启动失败。")
            if time.monotonic() >= deadline:
                pytest.fail("等待前端冒烟测试用 FastAPI 服务启动超时。")
            time.sleep(0.05)
        yield browser, origin, requests
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        if thread.is_alive():
            pytest.fail("前端冒烟测试用 FastAPI 服务未能正常退出。")


def test_login_and_primary_navigation_in_headless_browser(browser_app, tmp_path):
    browser, origin, requests = browser_app
    profile = tmp_path / "browser-profile"
    profile.mkdir()
    dom_path = tmp_path / "browser-dom.html"
    stderr_path = tmp_path / "browser-stderr.txt"
    command = [
        str(browser),
        "--headless=new",
        "--disable-gpu",
        "--disable-extensions",
        "--disable-background-networking",
        "--no-first-run",
        "--no-default-browser-check",
        "--no-proxy-server",
        f"--user-data-dir={profile}",
        "--virtual-time-budget=20000",
        "--dump-dom",
        f"{origin}/",
    ]
    if os.name != "nt":
        command.insert(1, "--no-sandbox")

    with (
        dom_path.open("w", encoding="utf-8") as dom_file,
        stderr_path.open("w", encoding="utf-8") as stderr_file,
    ):
        result = subprocess.run(
            command,
            stdout=dom_file,
            stderr=stderr_file,
            timeout=45,
            check=False,
        )

    dom = dom_path.read_text(encoding="utf-8")
    stderr = stderr_path.read_text(encoding="utf-8")
    assert result.returncode == 0, f"Chromium 退出码为 {result.returncode}：\n{stderr[-3000:]}"
    assert 'data-frontend-test="passed"' in dom, (
        f"登录到账户页的浏览器路径未通过。\n页面结果：{dom[-5000:]}\n"
        f"服务请求：{requests!r}\n浏览器日志：{stderr[-3000:]}"
    )
    assert 'data-frontend-test-path="login-to-accounts"' in dom
