# 可用主张与证据索引

| 可用主张 | 依据 | 不可外推 |
| --- | --- | --- |
| 全量pytest 235 passed（含前端浏览器冒烟1 passed） | evidence/verification-summary.md；tests/ | 不是235条真实模型任务或生产审计 |
| 曾做36条真实模型评测，结构检查35/36 | docs/agent-evaluation-results.md | 不是97.2%语义成功率；不覆盖新增工具 |
| 两种协议受控调用链 | test_agent_workflow.py、test_transfer_workflows.py | 测试使用模拟HTTP，不证明供应商持续可用 |
| 幂等/预算/隔离/未知恢复有测试 | test_banking.py、test_banking_edges.py | 不等于真实支付跨系统一致性 |
| 订阅取消后转固定金额的工作流有页面和后端约束 | contacts.py、workflows.py、截图说明 | 固定流程，不是无限制自动规划 |
| 日期场景计划仅保存日期和预算，创建时校验余额但不预留；下单须手动触发并待确认 | banking/scenarios.py、场景操作说明 | 不代表自动提醒、自动扣款或外部商户下单；Agent只读 |

截图只证明所示版本界面和对应受控操作，不证明模型泛化能力。每张图应随 captions 中的模式和数据说明使用。
