import json
import os
import time
from pathlib import Path
from tempfile import NamedTemporaryFile

from django.apps import AppConfig
from django.conf import settings


class LearningConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "learning"

    def ready(self):
        # Stamp build time on startup. Uses atomic write (temp file + rename)
        # so concurrent workers don't corrupt the file.
        path = Path(settings.BASE_DIR) / "version.json"
        info = {"version": "1.1.0", "build_time": ""}
        try:
            with open(path) as f:
                info = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        info["build_time"] = time.strftime("%Y-%m-%d %H:%M:%S")

        try:
            tmp = NamedTemporaryFile(
                mode="w", encoding="utf-8", delete=False, dir=path.parent
            )
            json.dump(info, tmp)
            tmp.close()
            os.replace(tmp.name, path)
        except OSError:
            pass
