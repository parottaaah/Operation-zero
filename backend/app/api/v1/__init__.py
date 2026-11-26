"""API v1 router aggregation."""

from fastapi import APIRouter

from app.api.v1 import (
    alerts,
    audit,
    auth,
    incidents,
    integrations,
    logs,
    services,
    webhooks,
    workspaces,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(workspaces.router)
api_router.include_router(services.router)
api_router.include_router(logs.router)
api_router.include_router(alerts.router)
api_router.include_router(incidents.router)
api_router.include_router(incidents.reports_router)
api_router.include_router(incidents.feedback_router)
api_router.include_router(integrations.router)
api_router.include_router(webhooks.router)
api_router.include_router(audit.router)

__all__ = ["api_router"]
