# AI-Banking

面向竞赛需求的本地可运行 AI Banking 演示版。提供中文对话工作台、六类金融场景、模拟银行工具和操作确认流。

## 当前实现

- 智能转账：联系人姓名、手机号或备注匹配；即时与预约转账；AA 收款单。
- 账单分析：消费分类、月度 / 年度已记录交易汇总和需人工核对的异常提示。
- 理财操作：按演示风险指标比较产品；申购、赎回前展示确认和风险说明。
- 卡片管理：申请演示数字卡、修改总额度和单日限额、锁定及解锁。
- 订阅管理：查看周期费用、续费日期；创建续费提醒或取消后续续费。
- 跨场景生日联动：预留模拟资金，并创建提前两天的礼物提醒。

对话解析使用本地中文规则与实体匹配，不调用外部大模型。页面和 JSON API 均在本机提供；所有账户、联系人、交易、理财产品及卡片均为虚构的内存数据。变更账户状态的操作必须先由用户确认。

## 启动

环境要求：Python 3.11 或更新版本。无第三方依赖、无密钥配置。

```powershell
python run.py
```

在浏览器打开启动信息显示的地址，默认是 `http://127.0.0.1:8765`。端口被占用时会尝试后续端口。按 `Ctrl+C` 停止服务；服务重启后演示状态会恢复初始样例。

## 验证

```powershell
python -m unittest discover -s tests -v
node --check src/ai_banking/web/app.js
```

## 本地 API

- `GET /api/health`：检查本地演示服务。
- `GET /api/state`：读取当前模拟账户状态。
- `POST /api/chat`：发送自然语言需求，例如 `{"message":"转 88 元给周明"}`。
- `POST /api/actions/{id}/confirm`：确认并执行待处理操作。
- `POST /api/actions/{id}/reject`：取消待处理操作。
- `POST /api/reset`：重置演示数据。

服务只绑定本机回环地址，不提供身份认证或真实金融接口，不应暴露到公网。预约转账在到期日首次读取账户状态时执行；页面每 15 秒刷新一次。服务重启会清空预约和其他变更。

## 项目文档

- [项目状态](PROJECT_STATUS.md)
- [项目需求](docs/requirements.md)
- [架构设计](docs/architecture.md)
- [比赛要求](docs/competition.md)
- [项目路线图](docs/roadmap.md)
- [协作规范](CONTRIBUTING.md)
