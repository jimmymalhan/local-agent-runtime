"""v1 API router — aggregates all endpoint modules."""
from fastapi import APIRouter

from app.api.v1.endpoints import items

api_router = APIRouter()


@api_router.get("/health", tags=["health"])
async def health_check() -> dict:
    """Liveness probe — returns 200 when the service is up."""
    return {"status": "ok"}


api_router.include_router(items.router, prefix="/items", tags=["items"])
