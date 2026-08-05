"""Template context processors."""

import json
from pathlib import Path

from django.conf import settings


def version_info(request):
    """Add version info to all template contexts."""
    path = Path(settings.BASE_DIR) / "version.json"
    try:
        with open(path) as f:
            info = json.load(f)
        return {"VERSION": info.get("version", "1.1.0"),
                "BUILD_TIME": info.get("build_time", "")}
    except (FileNotFoundError, json.JSONDecodeError):
        return {"VERSION": "dev", "BUILD_TIME": ""}
