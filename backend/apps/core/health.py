"""Health endpoints.

``/healthz`` is liveness — is this process alive? It must not touch the database,
or a database blip would make Kubernetes kill healthy application containers.
``/readyz`` is readiness — can this process actually serve traffic?
"""

from __future__ import annotations

from django.core.cache import cache
from django.db import connection
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt


@csrf_exempt
def liveness(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok"})


def _check_database() -> tuple[bool, str]:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return True, "ok"
    except Exception as exc:
        return False, f"{type(exc).__name__}"


def _check_cache() -> tuple[bool, str]:
    try:
        cache.set("readyz:probe", "1", 5)
        return (True, "ok") if cache.get("readyz:probe") == "1" else (False, "roundtrip failed")
    except Exception as exc:
        return False, f"{type(exc).__name__}"


def _check_migrations() -> tuple[bool, str]:
    try:
        from django.db.migrations.executor import MigrationExecutor

        executor = MigrationExecutor(connection)
        pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
        return (True, "ok") if not pending else (False, f"{len(pending)} pending")
    except Exception as exc:
        return False, f"{type(exc).__name__}"


@csrf_exempt
def readiness(request: HttpRequest) -> JsonResponse:
    checks = {
        "database": _check_database(),
        "cache": _check_cache(),
        "migrations": _check_migrations(),
    }
    healthy = all(ok for ok, _ in checks.values())
    return JsonResponse(
        {
            "status": "ok" if healthy else "degraded",
            "checks": {name: {"ok": ok, "detail": detail} for name, (ok, detail) in checks.items()},
        },
        status=200 if healthy else 503,
    )
