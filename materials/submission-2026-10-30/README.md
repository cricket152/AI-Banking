# AI-Banking 材料素材包

**供撰稿与PPT设计交接使用，未制作PPT、未上传，也未提交/推送代码。**

## 快速入口

- **[技术文档PDF、安全自评PDF及配套README/用例/部署说明](deliverables/README.md)**：本轮已生成的评审稿，优先使用此版本；原文字素材供追溯和后续答辩设计。
- v1.1重点图：[Agent运行与安全关卡](diagrams/agent-runtime.png)、[问题到12工具映射](diagrams/agent-tool-map.png)、[上下文压缩触发](diagrams/context-routing.png)，均附同名SVG矢量文件。
- [提交要求与待补项](submission-checklist.md)：按用户页面截图整理四项必交材料。
- [功能截图图册](images/index.html)：14张原始PNG；[逐图说明](images/captions.md)。
- [架构图PNG](diagrams/system-architecture.png)、[SVG矢量](diagrams/system-architecture.svg)、[交互HTML](diagrams/system-architecture.html)、[Archify编辑源](diagrams/architecture.archify.json)。
- [技术文档初稿](technical/technical-brief.md)、[核心机制与算法素材](technical/core-algorithms.md)、[工具/能力映射](technical/tool-and-capability-map.md)。
- [9分钟答辩提纲](defense/storyboard.md)、[演示讲解](defense/demo-script.md)、[设计选图表](defense/asset-map.md)。
- [安全自评初稿](security/self-assessment.md)：权限分级、控制依据、残余风险与待审查项。
- [源码审查ZIP](source/source-review.zip)、[部署与复现说明](source/README.md)、[归档哈希](source/archive-info.json)。
- [验证摘要](evidence/verification-summary.md)、[源码文件清单](evidence/source-manifest.json)、[截图环境复现](evidence/reproduce-screenshots.md)。

## 使用边界
基于分支codex/payees-transfer-workflow和基线2b63eba2539c787dc67b22f19a02ac92ba9c7fb9，包含本地尚未提交的功能。GitHub main不等于素材包代码。架构核心来源固定在已提交基线，增量通过当前源码清单独立标明。

全部资金和联系人为虚构。截图中的Agent明确标记为脚本化演示，工具与银行执行器实际运行；不是实时模型能力证明。历史35/36仅为固定样本结构检查，不能转写成97.2%业务成功率。当前222项自动化通过，不等于独立安全审计。

技术文档与安全自评已生成v1.1 PDF评审稿，配套README、测试用例、部署说明为Markdown；列示10项人工用例已由项目负责人确认审核通过。PPT仍由专业人士制作。后续补齐团队署名/分工、队友审查及全新依赖环境复现，冻结最终代码后更新归档。页面截图显示截止2026-11-02 18:00，可选项名称未显示。
