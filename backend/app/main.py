from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.api.compliance import router as compliance_router
from app.api.driver_reports import router as driver_reports_router
from app.api.drivers import router as drivers_router
from app.api.fuel import router as fuel_router
from app.api.health import router as health_router
from app.api.incidents import router as incidents_router
from app.api.inventory import router as inventory_router
from app.api.maintenance import router as maintenance_router
from app.api.purchase_orders import router as purchase_orders_router
from app.api.suppliers import router as suppliers_router
from app.api.trips import router as trips_router
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
app.include_router(inventory_router)
app.include_router(purchase_orders_router)
app.include_router(maintenance_router)
app.include_router(compliance_router)
app.include_router(trips_router)
app.include_router(driver_reports_router)
app.include_router(incidents_router)
