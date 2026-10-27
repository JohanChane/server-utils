import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any


def _strip_comments(text: str) -> str:
    lines = []
    for line in text.splitlines():
        stripped = re.sub(r"//.*$", "", line)
        stripped = re.sub(r"/\*.*?\*/", "", stripped)
        if stripped.strip():
            lines.append(stripped)
    return "\n".join(lines)


def load_config(path: Path | None = None) -> dict[str, Any]:
    if path is None:
        path = Path("config.jsonc")
    if not path.exists():
        raise FileNotFoundError(f"config not found: {path}")
    raw = path.read_text(encoding="utf-8")
    clean = _strip_comments(raw)
    try:
        return json.loads(clean)
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid JSON in {path}: {e}") from e


def iter_domains(config: dict[str, Any]) -> Iterator[tuple[str, str]]:
    default_reload_cmd = config.get("reload_cmd", "")
    for domain in config["domains"]:
        if isinstance(domain, str):
            yield domain, default_reload_cmd
        else:
            yield domain["domain"], domain.get("reload_cmd", default_reload_cmd)
