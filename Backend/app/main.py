from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.routes.bookings import router as bookings_router
from app.routes.health import router as health_router
from app.routes.local_test import router as local_test_router
from app.routes.twilio import router as twilio_router
from app.services.booking_provider import BookingProviderClient
from app.services.call_transfer import CallTransferService
from app.services.crm import CrmPmsClient
from app.storage.sqlite_store import SQLiteStore
from app.utils.logging import setup_logging

settings = get_settings()
setup_logging(settings.log_level)

store = SQLiteStore(settings.sqlite_path)
booking_provider = BookingProviderClient(settings.booking_provider_name)
crm_client = CrmPmsClient()
transfer_service = CallTransferService(settings.twilio_transfer_number)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await store.initialize()
    app.state.settings = settings
    app.state.store = store
    app.state.booking_provider = booking_provider
    app.state.crm_client = crm_client
    app.state.transfer_service = transfer_service
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(health_router)
app.include_router(bookings_router)
app.include_router(local_test_router)
app.include_router(twilio_router)
