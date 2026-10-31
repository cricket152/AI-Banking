# AI Banking 参赛材料

## 提交文件

四项必交文件与哈希见[成果提交索引](submission-index.md)。

- [答辩PPT](defense/AI-Banking-defense.pptx)：10页正文加2页备选附录，采用用户确认的制作成果。
- [技术文档](deliverables/technical-document.pdf)：竞赛提交版v1.2，系统架构、核心机制与安全设计。
- [安全自评](deliverables/security-self-assessment.pdf)：竞赛提交版v1.2，权限分级、已知风险与运行要求。
- [源码与部署材料](deliverables/source-and-deployment.zip)：功能源码、测试、配置示例与运行说明。
- [PPT制作素材包](deliverables/ppt-materials.zip)：交给PPT制作Agent使用；包含逐页DOCX指南、配文、讲稿和图片。本包为制作资料，不代替答辩PPT上传。

## 制作入口

从[ppt-kit/ppt-production-guide.docx](ppt-kit/ppt-production-guide.docx)开始，建议10页、8分40秒。结构化配文见[ppt-kit/slides.json](ppt-kit/slides.json)，截图与PNG/SVG图表位于ppt-kit/assets。

## 来源与范围

功能基线9389868，文档版本v1.2；源码包记录打包时Git HEAD与文件哈希。全部资金与联系人为虚构。14张功能截图使用独立虚构数据，涉及Agent的闭环为脚本化演示；工具与模拟执行器实际运行。自动化、人工流程和历史真实模型样本按各自范围列示。

此目录中的source、technical、security、evidence和defense保留历史采集与制作资料；本次交付入口为deliverables，PPT制作依据ppt-kit。defense/AI-Banking-defense.pptx已按ppt-kit指南重制为10页正文加2页备选附录，生成脚本为defense/create-defense-deck.py，本轮按用户指示作为答辩成果提交文件。
