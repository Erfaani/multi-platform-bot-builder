from django.apps import AppConfig


class FeaturesConfig(AppConfig):
    name = "apps.features"
    label = "features"
    verbose_name = "Feature catalogue"

    def ready(self) -> None:
        from apps.features import checks  # noqa: F401
