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
