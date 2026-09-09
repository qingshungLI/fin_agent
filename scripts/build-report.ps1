<#
报告构建管线：用项目 Python 生成矢量图，再从 docs 目录多遍编译 XeLaTeX。
源码与原始截图保留；任何制图或编译错误立即退出，避免把旧 PDF 当作新结果。
#>
param([string]$Python = '', [string]$XeLaTeX = 'xelatex')
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
if (-not $Python) { $Python = Join-Path $ProjectRoot '.venv-research\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $Python)) { throw "缺少 Python：$Python" }
$null = Get-Command $XeLaTeX -ErrorAction Stop
Push-Location $ProjectRoot
try {
    & $Python scripts/build_report_figures.py
    if ($LASTEXITCODE -ne 0) { throw '报告图片生成失败' }
    Push-Location (Join-Path $ProjectRoot 'docs')
    try {
        # 字体或图表变化会影响页码；三遍用于稳定目录、标签与浮动体引用。
        for ($Pass = 1; $Pass -le 3; $Pass++) {
            & $XeLaTeX -interaction=nonstopmode -halt-on-error AURORA_Alpha_Harness_Technical_Report.tex > "build-report-pass$Pass.log"
            if ($LASTEXITCODE -ne 0) {
                Get-Content -LiteralPath "build-report-pass$Pass.log" -Tail 30
                throw "LaTeX 第 $Pass 遍编译失败"
            }
        }
        Write-Output (Join-Path (Get-Location) 'AURORA_Alpha_Harness_Technical_Report.pdf')
    } finally { Pop-Location }
} finally { Pop-Location }