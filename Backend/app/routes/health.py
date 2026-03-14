from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(tags=["health"])


@router.get("/")
async def root(request: Request) -> dict[str, str]:
    settings = request.app.state.settings
    return {
        "app": settings.app_name,
        "status": "ok",
        "environment": settings.environment,
    }


@router.get("/healthz")
async def healthz(request: Request) -> dict[str, str]:
    settings = request.app.state.settings
    return {
        "status": "ok",
        "model": settings.openai_realtime_model,
    }
