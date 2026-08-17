from django.apps import AppConfig


class PlatformsConfig(AppConfig):
    name = "apps.platforms"
    label = "platforms"
    verbose_name = "Platform adapters"

    def ready(self) -> None:
        # Importing the adapters registers them (see registry.py).
        from apps.platforms import registry  # noqa: F401
