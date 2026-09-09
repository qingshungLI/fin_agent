# 技术报告增强版说明

本版更新主 PDF，并保留主源码及分章节源码。封面采用用户提供的项目原图，按 16:9 横向页面完整嵌入，正文保持 A4 纵向。

- `report_frontmatter.tex`：原始品牌封面、贡献总览与封面公式的实现口径说明。
- `report_innovation.tex`：研究合同、异质性子代、证据反馈三项贡献，以及明确标为待执行的消融方案。
- `report_results.tex`：停止快照、Core Lab 条件案例、父子区域对照与规律账本。
- `figures/brand_cover.png`：用户原始封面；`brand_cover.pdf` 为嵌入用静态资源。
- `figures/brand_cover_source.json`：封面来源和 SHA256。报告其余统计图来源见 `figures/sources.json`。

2026-09-09 停止快照为 15 个完成候选、6 个已评估子代，9 个 UNDECIDABLE、6 个 FAIL，独立确认数为 0。Core Lab 截图属于单独证据来源，不合并候选数，也不将训练区域 IC 转为收益改善倍数。

在仓库根目录运行 `powershell -ExecutionPolicy Bypass -File scripts/build-report.ps1` 可重建。封面 PNG/PDF 是随源码保留的静态资源，制图脚本不会覆盖它们。封面更换时应同步更新静态 PDF 和来源清单。PDF 修改前的备份位于 `artifacts/report-backups/`。