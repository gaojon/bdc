"""Load and read the application configuration JSON file.

Configuration is read once at startup and cached. Changes require a server
restart to take effect (D-42).

If the config file is missing or unparseable, a built-in default is returned
so the application can start.  Article generation will be unavailable until
a valid DeepSeek API key is configured.
"""

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "app_config.json"

# Built-in defaults used when app_config.json is absent or unreadable.
# These match config/app_config.example.json except the API key is empty —
# article generation will fail with a clear error until a real key is set.
DEFAULT_CONFIG: dict[str, Any] = {
    "deepseek": {
        "api_key": "",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "timeout_seconds": 120,
    },
    "article": {
        "target_word_count": 500,
        "min_hit_words": 25,
        "max_hit_words": 50,
        "max_word_pool_size": 500,
    },
    "limits": {
        "daily_generation_limit": 3,
        "article_history_retention": 24,
    },
    "spaced_repetition": {
        "intervals": [1, 3, 7, 21, 60],
    },
}


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    """Read and return the full config dictionary (cached in-process).

    Returns DEFAULT_CONFIG when the file is missing or invalid JSON so the
    application can still serve pages that don't depend on the API key.
    """
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning(
            "Config file not found at %s — using defaults. "
            "Article generation will fail until a valid DeepSeek API key is configured.",
            CONFIG_PATH,
        )
    except json.JSONDecodeError as e:
        logger.warning(
            "Config file %s has invalid JSON (%s) — using defaults.",
            CONFIG_PATH,
            e,
        )
    return DEFAULT_CONFIG


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
