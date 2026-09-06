from __future__ import annotations

import os
import sys
from pathlib import Path

import rqalpha


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    data_path = project_root / "data"
    credential_configured = bool(os.environ.get("RQDATAC2_CONF"))

    print(f"python={sys.version.split()[0]}")
    print(f"rqalpha={rqalpha.__version__}")
    print(f"data_path={data_path}")
    print(f"data_exists={data_path.exists()}")
    print(f"rqdatac_conf_configured={credential_configured}")

    if not credential_configured:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
