"""Root URL configuration.

Domain routes live in each app's `api/urls.py` and are mounted here under /api/v1/.
"""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.bot_runtime.webhooks import webhook
from apps.core.health import liveness, readiness

api_v1 = [
    path("auth/", include("apps.accounts.api.urls")),
    path("", include("apps.customers.api.urls")),
    path("", include("apps.core.api.urls")),
    # Phase 2 — public catalogue and the builder
    path("", include("apps.business_templates.api.urls")),
    path("", include("apps.features.api.urls")),
    path("", include("apps.orders.api.urls")),
    # Phase 3 — payments
    path("", include("apps.payments.api.urls")),
    path("", include("apps.notifications.api.urls")),
    # Phase 4 — bots
    path("", include("apps.bots.api.urls")),
    # Phase 6 — customer dashboard
    path("", include("apps.support.api.urls")),
    # Phase 10.5 — Telegram Mini App (end-user storefront/booking, initData-authenticated)
    path("", include("apps.miniapp.api.urls")),
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
]

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("api/v1/", include((api_v1, "v1"))),
    # Platform webhooks. Deliberately outside /api/: no auth middleware, no versioning,
    # and the URL is registered with the platform at provisioning time.
    path(
        "webhooks/<str:platform>/<uuid:instance_public_id>/",
        webhook,
        name="platform-webhook",
    ),
    path("healthz", liveness, name="healthz"),
    path("readyz", readiness, name="readyz"),
    # Prometheus scrape target. Not authenticated at the app layer — same posture as
    # /healthz and /readyz — so nginx (or the ingress) must keep it off the public edge
    # in production; see DEPLOYMENT.md §7.
    path("", include("django_prometheus.urls")),
]

if settings.DEBUG:  # pragma: no cover
    from django.conf.urls.static import static

    urlpatterns += [path("i18n/", include("django.conf.urls.i18n"))]
    # Dev-only stand-in for production's object storage/CDN (DEPLOYMENT.md §5). Scoped
    # to exactly the "public/" prefix product/property/course photos use — nothing else
    # under MEDIA_ROOT (receipts, AI documents) gets a route here or anywhere else;
    # see SECURITY.md §7.
    urlpatterns += static(
        settings.PUBLIC_MEDIA_URL, document_root=str(settings.MEDIA_ROOT / "public")
    )
