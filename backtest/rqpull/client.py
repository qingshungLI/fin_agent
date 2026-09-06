from __future__ import annotations

import os
import re
from pathlib import Path

from .config import PROJECT_ROOT

_ASSIGNMENT = re.compile(r"^(name|password|host|port)=(.*)$")


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def configure_credentials() -> str:
    """只从受控字段加载凭证，不打印、不持久化凭证值。"""
    if os.environ.get("RQDATAC2_CONF"):
        return "environment:RQDATAC2_CONF"

    make_sh = PROJECT_ROOT / "cache" / "make.sh"
    values: dict[str, str] = {}
    if make_sh.is_file():
        for line in make_sh.read_text(encoding="utf-8").splitlines():
            match = _ASSIGNMENT.fullmatch(line.strip())
            if match:
                values[match.group(1)] = _unquote(match.group(2))
        if all(values.get(k) for k in ("name", "password", "host", "port")):
            os.environ["RQDATAC2_CONF"] = (
                f"rqdata://{values['name']}:{values['password']}@"
                f"{values['host']}:{values['port']}"
            )
            return "cache/make.sh"

    raise RuntimeError("未找到可用 RQData 凭证；请恢复 cache/make.sh 或导出 RQDATAC2_CONF")


def init_rqdata():
    configure_credentials()
    import rqdatac

    try:
        import rqdatac_news  # noqa: F401
    except ImportError:
        pass
    rqdatac.init()
    return rqdatac

