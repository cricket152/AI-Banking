"""可选 LangSmith 观察层；仅上传脱敏副本，不参与业务、提示词或重试。"""

import json
from contextlib import contextmanager
from contextvars import ContextVar
from queue import Empty, Full, Queue
from threading import Event, Thread
from urllib.parse import urlsplit

from ai_banking.tracing import LOGGER, redact

CURRENT = ContextVar("banking_observation", default=None)


def _arguments(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return {"invalid_json": value}
    return value


def llm_output(content, calls, reasoning, usage):
    blocks = [{"type": "text", "text": content}] if content else []
    blocks.extend({"type": "reasoning", "text": value} for value in reasoning if value)
    blocks.extend(
        {"type": "tool_call", "id": call_id, "name": name, "args": _arguments(args)}
        for call_id, name, args in calls
    )
    output = {"messages": [{"role": "assistant", "content": blocks}]}
    if isinstance(usage, dict):
        counts = {}
        for name, alternatives in {
            "input_tokens": ("input_tokens", "prompt_tokens"),
            "output_tokens": ("output_tokens", "completion_tokens"),
            "total_tokens": ("total_tokens",),
        }.items():
            for key in alternatives:
                value = usage.get(key)
                if type(value) is int and value >= 0:
                    counts[name] = value
                    break
        details = usage.get("output_tokens_details") or usage.get("completion_tokens_details")
        if (
            isinstance(details, dict)
            and type(details.get("reasoning_tokens")) is int
            and details["reasoning_tokens"] >= 0
        ):
            counts["output_token_details"] = {"reasoning": details["reasoning_tokens"]}
        details = usage.get("input_tokens_details") or usage.get("prompt_tokens_details")
        cached = details.get("cached_tokens") if isinstance(details, dict) else None
        cached = usage.get("prompt_cache_hit_tokens", cached)
        if type(cached) is int and cached >= 0:
            counts["input_token_details"] = {"cache_read": cached}
        if counts:
            output["usage_metadata"] = counts
    return output


def llm_inputs(messages):
    """仅转换追踪副本，保留真实请求和 chat template。"""
    result = []
    for message in messages:
        kind = message.get("type")
        if kind == "function_call":
            result.extend(
                llm_output(
                    None,
                    [(message["call_id"], message["name"], message["arguments"])],
                    [],
                    None,
                )["messages"]
            )
        elif kind == "function_call_output":
            result.append(
                {"role": "tool", "tool_call_id": message["call_id"], "content": message["output"]}
            )
        elif kind == "reasoning":
            visible = [
                p.get("text", "")
                for p in (message.get("summary") or []) + (message.get("content") or [])
                if p.get("type") in {"summary_text", "reasoning_text"}
            ]
            if visible:
                result.extend(llm_output(None, [], visible, None)["messages"])
        elif message.get("role") or kind == "message":
            item = {
                key: message[key] for key in ("role", "content", "tool_call_id") if key in message
            }
            item.setdefault("role", "assistant")
            if message.get("tool_calls") or message.get("reasoning_content"):
                calls = [
                    (c["id"], c["function"]["name"], c["function"]["arguments"])
                    for c in message.get("tool_calls", [])
                ]
                item = llm_output(
                    message.get("content"), calls, [message.get("reasoning_content")], None
                )["messages"][0]
            if kind == "message" and isinstance(item.get("content"), list):
                item["content"] = [
                    {"type": "text", "text": part.get("text", "")}
                    for part in item["content"]
                    if part.get("type") in {"output_text", "text"}
                ]
            result.append(item)
    return {"messages": result}


class Observation:
    def __init__(self, observer, run):
        self.observer, self.run = observer, run
        self.outputs, self.error = None, None

    def output(self, value, error=None):
        if self.run:
            try:
                self.outputs = self.observer.safe(value)
                self.error = error
            except Exception:
                self.observer.failed += 1
                LOGGER.warning("[LangSmith] 输出整理失败；业务继续。")


class Observer:
    def __init__(self, settings):
        self.settings = settings
        self.client, self.run_type, self.worker = None, None, None
        self.pending = Queue(maxsize=32)
        self.stopping = Event()
        self.sent, self.failed, self.dropped = 0, 0, 0
        self.state = "disabled"

    def start(self):
        if not self.settings.langsmith_enabled or (self.worker and self.worker.is_alive()):
            return
        try:
            from langsmith import Client
            from langsmith.run_trees import RunTree
            from urllib3.util.retry import Retry

            self.client = Client(
                api_key=self.settings.langsmith_key,
                api_urls={self.settings.langsmith_endpoint: self.settings.langsmith_key},
                workspace_id=self.settings.langsmith_workspace,
                auto_batch_tracing=False,
                omit_traced_runtime_info=True,
                tracing_mode="langsmith",
                tracing_sampling_rate=1,
                timeout_ms=1500,
                retry_config=Retry(total=0),
                info={},
            )
            self.run_type = RunTree
            self.state = "ready"
            self.stopping.clear()
            self.worker = Thread(target=self._export, name="bank-langsmith", daemon=True)
            self.worker.start()
        except ImportError:
            self.state = "missing_sdk"
            LOGGER.warning(
                "[LangSmith] 未安装可选 SDK，请安装 .[observability]；继续使用本地日志。"
            )
        except Exception:
            self.state = "initialization_error"
            LOGGER.warning("[LangSmith] 初始化失败；继续使用本地日志，未输出凭据或异常正文。")

    def safe(self, value, *, metadata=False):
        if not metadata and not self.settings.langsmith_content:
            return redact(
                {
                    "content": "[内容输出已关闭]",
                    **(
                        {"usage_metadata": value["usage_metadata"]}
                        if "usage_metadata" in value
                        else {}
                    ),
                },
                (self.settings.model_key, self.settings.langsmith_key),
            )

        # 不把任意对象交给 SDK 自动序列化，以免 Settings / 会话对象意外进入追踪。
        def primitives(item):
            if item is None or type(item) in (str, int, float, bool):
                return item
            if isinstance(item, dict):
                return {str(key): primitives(v) for key, v in item.items()}
            if isinstance(item, (list, tuple)):
                return [primitives(v) for v in item]
            return "[未采集对象]"

        return redact(primitives(value), (self.settings.model_key, self.settings.langsmith_key))

    @contextmanager
    def span(self, name, run_type="chain", *, inputs=None, metadata=None):
        run = None
        parent = CURRENT.get()
        if self.run_type and not self.stopping.is_set():
            try:
                values = {
                    "name": name,
                    "run_type": run_type,
                    "inputs": self.safe(inputs() if callable(inputs) else inputs or {}),
                    "extra": {"metadata": self.safe(metadata or {}, metadata=True)},
                }
                if parent and parent[0] is self and parent[1] is not None:
                    run = parent[1].create_child(**values)
                else:
                    run = self.run_type(
                        **values,
                        project_name=self.settings.langsmith_project,
                        ls_client=self.client,
                        replicas=[],
                        tags=["ai-banking", "simulated"],
                    )
            except Exception:
                self.failed += 1
                LOGGER.warning("[LangSmith] 追踪构造失败；业务继续，未重试业务操作。")
        token = CURRENT.set((self, run))
        observation = Observation(self, run)
        try:
            yield observation
        except BaseException as error:
            observation.error = getattr(error, "code", type(error).__name__)
            raise
        finally:
            CURRENT.reset(token)
            if run:
                try:
                    error = self.safe({"code": observation.error}, metadata=True)["code"]
                    run.end(outputs=observation.outputs, error=error)
                    if not (parent and parent[0] is self and parent[1] is not None):
                        self.pending.put_nowait(run)
                except Full:
                    self.dropped += 1
                    LOGGER.warning("[LangSmith] 上传队列已满，丢弃本次追踪；业务继续。")
                except Exception:
                    self.failed += 1
                    LOGGER.warning("[LangSmith] 追踪收尾失败；业务继续。")

    def _export(self):
        try:
            while not self.stopping.is_set() or not self.pending.empty():
                try:
                    run = self.pending.get(timeout=0.2)
                except Empty:
                    continue
                try:
                    run.post(exclude_child_runs=False)
                    self.sent += 1
                    self.state = "connected"
                except Exception:
                    self.failed += 1
                    self.state = "upload_error"
                    LOGGER.warning(
                        "[LangSmith] 上传失败，请检查密钥、区域、权限或网络；"
                        "业务未重试，未输出异常正文。"
                    )
                finally:
                    self.pending.task_done()
        finally:
            try:
                self.client.close(timeout=1)
            except Exception:
                LOGGER.warning("[LangSmith] 客户端收尾失败，未输出异常正文。")

    def close(self, timeout=2):
        self.stopping.set()
        if self.worker:
            self.worker.join(timeout=timeout)
            if self.worker.is_alive():
                LOGGER.warning("[LangSmith] 退出等待已结束，未上传的调试追踪可能丢失。")

    def status(self):
        return {
            "enabled": self.settings.langsmith_enabled,
            "status": self.state,
            "sent_traces": self.sent,
            "failed_traces": self.failed,
            "dropped_traces": self.dropped,
        }

    def model_metadata(self):
        host = urlsplit(self.settings.model_url).hostname or ""
        provider = {"api.deepseek.com": "deepseek", "api.openai.com": "openai"}.get(host, "custom")
        return {
            "ls_provider": provider,
            "ls_model_name": self.settings.model,
            "api": self.settings.model_api,
        }


def main():
    import argparse

    from ai_banking.config import Settings
    from ai_banking.tracing import configure_terminal

    configure_terminal()
    parser = argparse.ArgumentParser(
        description="上传一条合成 LangSmith 自检追踪，不调用模型或银行"
    )
    parser.add_argument("command", choices=["check"])
    parser.parse_args()
    try:
        settings = Settings.from_env()
    except ValueError as error:
        parser.exit(2, f"配置错误：{error}\n")
    if not settings.langsmith_enabled:
        parser.exit(2, "LangSmith 未开启，请先设置 LANGSMITH_TRACING=true。\n")
    observer = Observer(settings)
    observer.start()
    if observer.state != "ready":
        parser.exit(1, "LangSmith 尚未就绪，请检查可选依赖及配置。\n")
    with observer.span(
        "LangSmith 连接自检",
        inputs={"message": "AI-Banking 合成连接测试；未调用模型和银行"},
        metadata={"check": "connectivity", "simulated": True},
    ) as span:
        span.output({"result": "合成自检追踪"})
    observer.close(timeout=5)
    if observer.sent != 1:
        parser.exit(1, "尚未确认上传成功，请检查密钥、区域、工作区权限和网络。\n")
    print("上传成功。请在 LangSmith 目标项目中查看“LangSmith 连接自检”。")


if __name__ == "__main__":
    main()
