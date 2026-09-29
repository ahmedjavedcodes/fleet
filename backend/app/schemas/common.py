from pydantic import BaseModel


class VehicleDriverRefs(BaseModel):
    """Flat vehicle/driver display fields joined onto operational records, so
    list/detail responses never force the client (or an AI agent) into a second
    lookup just to show a plate or a driver's name. Populated from the ORM
    model's VehicleDriverRefMixin properties; driver_name is None for records
    with no driver attached."""

    vehicle_plate: str | None = None
    vehicle_make: str | None = None
    vehicle_model: str | None = None
    vehicle_name: str | None = None
    driver_name: str | None = None
