from django.apps import AppConfig


class BotRuntimeConfig(AppConfig):
    name = "apps.bot_runtime"
    label = "bot_runtime"
    verbose_name = "Bot runtime"

    def ready(self) -> None:
        # Importing each app's `handlers` module runs the registration decorators, so a
        # feature becomes routable simply by existing.
        from apps.bot_runtime.handlers import load_feature_handlers

        load_feature_handlers()
