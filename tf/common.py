from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SNAPSHOTS = DATA / "snapshots"
KST = ZoneInfo("Asia/Seoul")


def today() -> str:
    """Collection date in KST (the daily run fires at 08:47 KST)."""
    return dt.datetime.now(KST).date().isoformat()


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text())


def dump(path: Path, obj: Any, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if compact:
        text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    else:
        text = json.dumps(obj, ensure_ascii=False, indent=2)
    path.write_text(text + "\n")
