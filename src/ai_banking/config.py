"""只从服务端环境读取配置，不向浏览器暴露凭据。"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    database: Path = Path(".local/banking.sqlite3")
    origin: str = "http://127.0.0.1:8000"
    local_http: bool = False
    agent_mode: str = "offline"
    model_url: str = "https://api.openai.com/v1"
    model_api: str = "responses"
    model: str = ""
    model_key: str = field(default="", repr=False)
    trace_enabled: bool = True
    trace_content: bool = True
    max_output_tokens: int = 1500
    langsmith_enabled: bool = False
    langsmith_key: str = field(default="", repr=False)
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    langsmith_project: str = "ai-banking-local"
    langsmith_workspace: str = ""
    langsmith_content: bool = True
    idle_seconds: int = 900
    absolute_seconds: int = 28800

    def __post_init__(self):
        origin = urlsplit(self.origin)
        if self.local_http and (
            origin.scheme != "http" or origin.hostname not in {"127.0.0.1", "localhost", "::1"}
        ):
            raise ValueError("BANK_LOCAL_HTTP 仅可用于回环地址的 HTTP 环境")
        if (
            origin.scheme not in {"http", "https"}
            or not origin.hostname
            or origin.username
            or origin.password
            or origin.path
            or origin.query
            or origin.fragment
        ):
            raise ValueError("BANK_ORIGIN 必须是无路径的明确 Origin")
        if origin.scheme == "http" and not (
            self.local_http and origin.hostname in {"127.0.0.1", "localhost", "::1"}
        ):
            raise ValueError("HTTP 仅允许显式开启的本机回环环境")
        if self.agent_mode not in {"offline", "model"}:
            raise ValueError("AGENT_MODE 仅支持 offline 或 model")
        if self.model_api not in {"responses", "chat"}:
            raise ValueError("MODEL_API 仅支持 responses 或 chat")
        if self.agent_mode == "model":
            endpoint = urlsplit(self.model_url)
            if not self.model or not self.model_key:
                raise ValueError("模型模式需要 MODEL_NAME 和 MODEL_API_KEY")
            if (
                endpoint.scheme != "https"
                or not endpoint.hostname
                or endpoint.username
                or endpoint.password
                or endpoint.query
                or endpoint.fragment
            ):
                raise ValueError("模型端点必须使用 HTTPS，凭据只能通过独立配置提供")
        if self.idle_seconds <= 0 or self.absolute_seconds <= 0:
            raise ValueError("会话有效期必须为正数")
        if not 256 <= self.max_output_tokens <= 16384:
            raise ValueError("MODEL_MAX_OUTPUT_TOKENS 必须为 256–16384")
        if self.langsmith_enabled:
            endpoint = urlsplit(self.langsmith_endpoint)
            if not self.langsmith_key.strip():
                raise ValueError("开启 LangSmith 需要 LANGSMITH_API_KEY，请在本地 .env 配置")
            if (
                endpoint.scheme != "https"
                or not endpoint.hostname
                or endpoint.username
                or endpoint.password
                or endpoint.query
                or endpoint.fragment
            ):
                raise ValueError("LANGSMITH_ENDPOINT 必须为不含凭据和查询参数的 HTTPS 地址")
            if not self.langsmith_project.strip() or len(self.langsmith_project) > 128:
                raise ValueError("LANGSMITH_PROJECT 必须为 1–128 字符的项目名称")

    @classmethod
    def from_env(cls):
        load_dotenv(override=False)
        return cls(
            database=Path(os.getenv("BANK_DATABASE", ".local/banking.sqlite3")),
            origin=os.getenv("BANK_ORIGIN", "http://127.0.0.1:8000"),
            local_http=os.getenv("BANK_LOCAL_HTTP", "false").lower() == "true",
            agent_mode=os.getenv("AGENT_MODE", "offline"),
            model_url=os.getenv("MODEL_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            model_api=os.getenv("MODEL_API", "responses"),
            model=os.getenv("MODEL_NAME", ""),
            model_key=os.getenv("MODEL_API_KEY", ""),
            trace_enabled=os.getenv("AGENT_TRACE_ENABLED", "true").lower() == "true",
            trace_content=os.getenv("AGENT_TRACE_CONTENT", "true").lower() == "true",
            max_output_tokens=int(os.getenv("MODEL_MAX_OUTPUT_TOKENS", "1500")),
            langsmith_enabled=os.getenv("LANGSMITH_TRACING", "false").lower() == "true",
            langsmith_key=os.getenv("LANGSMITH_API_KEY", ""),
            langsmith_endpoint=os.getenv(
                "LANGSMITH_ENDPOINT", "https://api.smith.langchain.com"
            ).rstrip("/"),
            langsmith_project=os.getenv("LANGSMITH_PROJECT", "ai-banking-local"),
            langsmith_workspace=os.getenv("LANGSMITH_WORKSPACE_ID", ""),
            langsmith_content=os.getenv("LANGSMITH_TRACE_CONTENT", "true").lower() == "true",
        )
