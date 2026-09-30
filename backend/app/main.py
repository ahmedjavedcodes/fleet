from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.assignments import router as assignments_router
from app.api.auth import router as auth_router
from app.api.compliance import router as compliance_router
from app.api.dashboard import router as dashboard_router
from app.api.documents import router as documents_router
from app.api.driver_reports import router as driver_reports_router
from app.api.drivers import router as drivers_router
from app.api.fuel import router as fuel_router
from app.api.health import router as health_router
from app.api.incidents import router as incidents_router
from app.api.inventory import router as inventory_router
from app.api.maintenance import router as maintenance_router
from app.api.memory import router as memory_router
from app.api.notifications import router as notifications_router
from app.api.purchase_orders import router as purchase_orders_router
from app.api.suppliers import router as suppliers_router
from app.api.trips import router as trips_router
from app.api.uploads import router as uploads_router
from app.api.vehicles import router as vehicles_router
from app.core.config import get_settings
from app.services.upload_service import INCIDENT_IMAGE_URL_PREFIX, incident_image_dir

settings = get_settings()

app = FastAPI(title="Fleet Management API", debug=settings.debug)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
app.include_router(dashboard_router)
app.include_router(assignments_router)
app.include_router(memory_router)
app.include_router(documents_router)
app.include_router(notifications_router)
app.include_router(uploads_router)

# Only the incidents folder is public (unguessable UUID names); fuel receipts and
# documents under the same upload_dir stay private.
incident_image_dir().mkdir(parents=True, exist_ok=True)
app.mount(INCIDENT_IMAGE_URL_PREFIX, StaticFiles(directory=incident_image_dir()), name="incident-images")
