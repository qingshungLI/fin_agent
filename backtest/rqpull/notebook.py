from __future__ import annotations

from pathlib import Path

import nbformat as nbf

from .config import DATA_ROOT, PROJECT_ROOT


def create_sanity_notebook() -> Path:
    output = PROJECT_ROOT / "cache" / "notebooks" / "00_sanity_check.ipynb"
    output.parent.mkdir(parents=True, exist_ok=True)
    nb = nbf.v4.new_notebook()
    nb["metadata"]["kernelspec"] = {"display_name": "sentiment RQData (.venv)", "language": "python", "name": "sentiment-rqdata"}
    nb["cells"] = [
        nbf.v4.new_markdown_cell("# RQData 本地仓库体检\n\n本 Notebook 只查询 Parquet/DuckDB，不调用远程 API。"),
        nbf.v4.new_code_cell(
            "from pathlib import Path\nimport duckdb, pandas as pd\n"
            f"DATA_ROOT = Path({str(DATA_ROOT)!r})\n"
            "con = duckdb.connect(str(DATA_ROOT / 'warehouse.duckdb'), read_only=True)\n"
            "con.sql('SELECT * FROM _catalog ORDER BY view_name').show()"
        ),
        nbf.v4.new_markdown_cell("## 日线覆盖度"),
        nbf.v4.new_code_cell(
            "daily_coverage = con.sql('''\n"
            "SELECT date, count(DISTINCT order_book_id) AS stocks\n"
            "FROM v_daily_bar GROUP BY date ORDER BY date\n''').df()\n"
            "daily_coverage.plot(x='date', y='stocks', figsize=(14,4), title='每日股票覆盖数')"
        ),
        nbf.v4.new_markdown_cell("## 缺失率"),
        nbf.v4.new_code_cell(
            "con.sql('''SELECT\n"
            "avg((open IS NULL)::INTEGER)::DOUBLE AS open_missing,\n"
            "avg((close IS NULL)::INTEGER)::DOUBLE AS close_missing,\n"
            "avg((volume IS NULL)::INTEGER)::DOUBLE AS volume_missing,\n"
            "avg((num_trades IS NULL)::INTEGER)::DOUBLE AS num_trades_missing\n"
            "FROM v_daily_bar''').df()"
        ),
        nbf.v4.new_markdown_cell("## 复权收益率校准"),
        nbf.v4.new_code_cell(
            "import json\n"
            "calibration = json.loads((DATA_ROOT / '_state' / 'validation_return_calibration.json').read_text())\n"
            "calibration"
        ),
        nbf.v4.new_markdown_cell("## 新闻月度条数（新闻完成后运行）"),
        nbf.v4.new_code_cell(
            "if con.sql(\"SELECT count(*) FROM _catalog WHERE view_name='v_news_meta'\").fetchone()[0]:\n"
            "    display(con.sql(\"SELECT date_trunc('month', datetime) month, count(*) rows FROM v_news_meta GROUP BY 1 ORDER BY 1\").df())"
        ),
    ]
    nbf.write(nb, output)
    return output
