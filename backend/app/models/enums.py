import enum


class SubscriptionTier(str, enum.Enum):
    trial = "trial"
    starter = "starter"
    pro = "pro"
    enterprise = "enterprise"


class UserRole(str, enum.Enum):
    admin = "admin"
    fleet_manager = "fleet_manager"
    driver = "driver"
    mechanic = "mechanic"


class DriverStatus(str, enum.Enum):
    active = "active"
    suspended = "suspended"
    inactive = "inactive"


class VehicleFuelType(str, enum.Enum):
    diesel = "diesel"
    petrol = "petrol"
    hybrid = "hybrid"
    electric = "electric"


class VehicleStatus(str, enum.Enum):
    active = "active"
    maintenance = "maintenance"
    retired = "retired"


class FuelReceiptUploadStatus(str, enum.Enum):
    pending = "pending"
    parsed = "parsed"
    failed = "failed"


class PurchaseOrderStatus(str, enum.Enum):
    pending = "pending"
    shipped = "shipped"
    received = "received"
    cancelled = "cancelled"


class ServiceType(str, enum.Enum):
    """Shared identically between ComplianceRule and MaintenanceLog -- the same
    nine values in both places, never diverging."""

    oil_change = "oil_change"
    brake_service = "brake_service"
    tire_rotation = "tire_rotation"
    engine_repair = "engine_repair"
    transmission = "transmission"
    electrical = "electrical"
    body_work = "body_work"
    general_inspection = "general_inspection"
    other = "other"


class VehicleCondition(str, enum.Enum):
    good = "good"
    fair = "fair"
    poor = "poor"


class IncidentType(str, enum.Enum):
    damage = "damage"
    violation = "violation"
    near_miss = "near_miss"


class IncidentSeverity(str, enum.Enum):
    minor = "minor"
    moderate = "moderate"
    severe = "severe"
    critical = "critical"


class IncidentResolutionStatus(str, enum.Enum):
    open = "open"
    investigating = "investigating"
    resolved = "resolved"
    closed = "closed"


class AgentMessageRole(str, enum.Enum):
    user = "user"
    assistant = "assistant"


class MemoryScope(str, enum.Enum):
    personal = "personal"
    organization = "organization"
    entity = "entity"


class MemoryEntityType(str, enum.Enum):
    vehicle = "vehicle"
    driver = "driver"
