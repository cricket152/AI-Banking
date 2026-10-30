# AI-Banking 材料素材包

**材料审校稿：含可编辑答辩PPTX；未上传或正式提交。团队与签署信息仍待补。**

## 快速入口

- **[交付说明、用例与部署指南](deliverables/README.md)**：当前说明以已修订的Markdown为准；PDF仍是2026-10-30历史导出，修订源稿后尚未重导，不应作为最终提交版。
- 流程图：[Agent运行与安全关卡](diagrams/agent-runtime.png)、[问题到12工具映射](diagrams/agent-tool-map.png)、[上下文压缩触发](diagrams/context-routing.png)，均附同名SVG矢量文件。
- [提交要求与待补项](submission-checklist.md)：按用户页面截图整理四项必交材料。
- [功能截图图册](images/index.html)：14张原始PNG；[逐图说明](images/captions.md)。
- [架构图PNG](diagrams/system-architecture.png)、[SVG矢量](diagrams/system-architecture.svg)、[交互HTML](diagrams/system-architecture.html)、[Archify编辑源](diagrams/architecture.archify.json)。
- [技术文档初稿](technical/technical-brief.md)、[核心机制与算法素材](technical/core-algorithms.md)、[工具/能力映射](technical/tool-and-capability-map.md)。
- [10页、预计讲解8分40秒的故事板](defense/storyboard.md)、[可编辑中文答辩PPTX](defense/AI-Banking-defense.pptx)、[演示讲解](defense/demo-script.md)、[设计选图表](defense/asset-map.md)。
- [安全自评初稿](security/self-assessment.md)：权限分级、控制依据、残余风险与待审查项。
- [历史源码审查ZIP](source/source-review.zip)、[历史归档说明](source/README.md)、[归档哈希](source/archive-info.json)；该ZIP并非当前冻结源码，正式提交前需按冻结版本重新打包。
- [验证摘要](evidence/verification-summary.md)、[源码文件清单](evidence/source-manifest.json)、[截图环境复现](evidence/reproduce-screenshots.md)。

## 使用边界
本材料目录包含2026-10-30来源快照；历史源码ZIP和图表中的分支/基线标识仅用于溯源，不代表当前Git HEAD或当前冻结交付。当前代码状态以根目录PROJECT_STATUS.md为准；提交前需按冻结版本重新打包并复核材料、源码和哈希。

全部资金和联系人为虚构。截图中的Agent明确标记为脚本化演示，工具与银行执行器实际运行；不是实时模型能力证明。历史35/36仅为固定样本结构检查，不能转写成97.2%业务成功率；新增卡片、场景和理财专项真实模型评测未运行/未完成。当前工作树全量自动化为235项通过（含前端浏览器冒烟1项），不等于独立安全审计。

列示10项人工用例已由项目负责人确认审核通过；独立队友审查尚未完成。Python 3.12+为最低要求，本机没有3.12解释器；当前3.14.6环境全量235项通过，另以新建Python 3.13环境按锁文件安装并完成`pip check`及39项核心/前端定向测试，不等于3.12或全新机器验收。团队姓名、分工和签署信息保留TODO。技术/安全PDF仍为历史导出，需从当前修订源稿重新生成后再提交。页面截图显示截止2026-11-02 18:00，但时区和可选项名称均未显示，保留TODO。
