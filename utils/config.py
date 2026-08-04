"""Load and read the application configuration JSON file.

Configuration is read once at startup and cached. Changes require a server
restart to take effect (D-42).
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "app_config.json"


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    """Read and return the full config dictionary (cached in-process)."""
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def get_config(key: str, default: Any = None) -> Any:
    """Retrieve a nested config value via dot-delimited key.

    Example:
        get_config("article.target_word_count")  # -> 500
        get_config("limits.daily_generation_limit", default=3)
    """
    cfg = load_config()
    for part in key.split("."):
        if isinstance(cfg, dict):
            cfg = cfg.get(part)
        else:
            return default
        if cfg is None:
            return default
    return cfg
