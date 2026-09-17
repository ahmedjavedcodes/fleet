from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.api.drivers import router as drivers_router
from app.api.fuel import router as fuel_router
from app.api.health import router as health_router
from app.api.suppliers import router as suppliers_router
from app.api.vehicles import router as vehicles_router
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(title="Fleet Management API", debug=settings.debug)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(vehicles_router)
app.include_router(drivers_router)
app.include_router(suppliers_router)
app.include_router(fuel_router)
