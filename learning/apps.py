from django.apps import AppConfig


class LearningConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "learning"

    def ready(self):
        # Update build timestamp on every startup
        import json
        import time
        from pathlib import Path
        from django.conf import settings

        path = Path(settings.BASE_DIR) / "version.json"
        info = {"version": "1.0.0", "build_time": ""}
        try:
            with open(path) as f:
                info = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        info["build_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(path, "w") as f:
            json.dump(info, f)
