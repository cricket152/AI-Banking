# 可用主张与证据索引

| 可用主张 | 依据 | 不可外推 |
| --- | --- | --- |
| 222项自动化通过 | PROJECT_STATUS.md 2026-10-30；tests/ | 不是222条真实模型任务或生产审计 |
| 曾做36条真实模型评测，结构检查35/36 | docs/agent-evaluation-results.md | 不是97.2%语义成功率；不覆盖新增工具 |
| 两种协议受控调用链 | test_agent_workflow.py、test_transfer_workflows.py | 测试使用模拟HTTP，不证明供应商持续可用 |
| 幂等/预算/隔离/未知恢复有测试 | test_banking.py、test_banking_edges.py | 不等于真实支付跨系统一致性 |
| 新方案有页面和后端约束 | contacts.py、workflows.py、截图说明 | 固定流程，不是无限制自动规划 |

截图只证明所示版本界面和对应受控操作，不证明模型泛化能力。每张图应随 captions 中的模式和数据说明使用。
