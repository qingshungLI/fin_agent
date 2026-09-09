# 阶段成果与报告重建

`report/` 中四张 PNG 为用户提供的 Core Lab 原始截图，保持原图未修改。

- `factor_1.png`：条件候选 CORE170-8EB14F14ED32、父子增量与分段统计。
- `factor_2.png`：该候选的发现后经济机制解释。
- `all_factor_show.png`：部分候选的 promote / observe / drop 记录，不是完整候选库。
- `law.png`：规律账本片段，含剔除理由、证据冲突和验证限制。
- `evidence-transcription.json`：从第一张案例图人工核对转录的数值，仅用于图表排版，未进行独立复算。

这些截图与 `docs/research/2026-09-09-results.json` 是两组来源，报告分别呈现。不要将它们拼接为一个批次的收益或候选总数。转录以原图为依据，缺少原始序列时不补造置信区间。

最终报告位于 `docs/AURORA_Alpha_Harness_Technical_Report.pdf`，主源码及两个分章节源码均在 `docs/`。报告图使用 Matplotlib 生成矢量 PDF 和 PNG 预览；来源 SHA256 清单在 `docs/figures/sources.json`。

从仓库根目录重建：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build-report.ps1
```

需要项目 Python 环境中的 Matplotlib、XeLaTeX、TeX Gyre Termes、宋体及微软雅黑。制图入口是 `scripts/build_report_figures.py`；更换机器时可传入 `-Python` 指定解释器。