from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "apps.core"
    label = "core"
    verbose_name = "Core"

    def ready(self) -> None:
        from apps.core import celery_signals, checks, tenant_session  # noqa: F401
        from apps.core.logging import configure_structlog
        from apps.core.metrics import register_queue_depth_collector

        tenant_session.register()
        celery_signals.register()
        configure_structlog()
        register_queue_depth_collector()
