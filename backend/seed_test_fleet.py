"""Provision the "Test Fleet" organization with an admin, two fleet managers and five
drivers (each driver with a linked Driver profile).

    python seed_test_fleet.py

Safe to run alongside other organizations; refuses to run if the "test-fleet" slug
already exists. Only the bcrypt hash of the password is stored in the database --
the shared demo password below is a throwaway for local testing.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.driver import Driver
from app.models.enums import DriverStatus, UserRole
from app.models.organization import Organization
from app.models.user import User

ORG_NAME = "Test Fleet"
ORG_SLUG = "test-fleet"
DOMAIN = "test-fleet.com"
DEMO_PASSWORD = "Demo1234!"
LICENSE_VALID_YEARS = 10

STAFF = [
    (UserRole.admin, "admin", "Test Admin"),
    (UserRole.fleet_manager, "fm1", "Farah Siddiqui"),
    (UserRole.fleet_manager, "fm2", "Hamza Malik"),
]

# (email prefix, full name, phone, license no, license type, issue date)
DRIVERS = [
    ("driver1", "Imran Sheikh", "+92-300-2010001", "TF-DL-2001", "HTV", date(2019, 3, 12)),
    ("driver2", "Nadia Hussain", "+92-321-2010002", "TF-DL-2002", "LTV", date(2021, 7, 5)),
    ("driver3", "Kamran Aslam", "+92-333-2010003", "TF-DL-2003", "HTV", date(2018, 11, 28)),
    ("driver4", "Sana Mirza", "+92-345-2010004", "TF-DL-2004", "LTV", date(2022, 1, 19)),
    ("driver5", "Tariq Butt", "+92-311-2010005", "TF-DL-2005", "HTV", date(2020, 9, 2)),
]


def add_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # Feb 29
        return d.replace(year=d.year + years, day=28)


def main() -> None:
    hashed = hash_password(DEMO_PASSWORD)
    with SessionLocal() as db:
        if db.execute(select(Organization).where(Organization.slug == ORG_SLUG)).scalar_one_or_none():
            raise SystemExit(f"Organization '{ORG_SLUG}' already exists -- nothing to do.")

        org = Organization(id=uuid.uuid4(), name=ORG_NAME, slug=ORG_SLUG)
        db.add(org)
        db.flush()

        def new_user(role: UserRole, prefix: str, full_name: str, phone: str | None = None) -> User:
            user = User(
                id=uuid.uuid4(),
                organization_id=org.id,
                email=f"{prefix}@{DOMAIN}",
                hashed_password=hashed,
                full_name=full_name,
                phone=phone,
                role=role,
            )
            db.add(user)
            return user

        staff = [new_user(role, prefix, name) for role, prefix, name in STAFF]
        driver_users = [
            (new_user(UserRole.driver, prefix, name, phone), name, phone, license_no, license_type, issued)
            for prefix, name, phone, license_no, license_type, issued in DRIVERS
        ]
        db.flush()

        admin = staff[0]
        for user, name, phone, license_no, license_type, issued in driver_users:
            db.add(
                Driver(
                    id=uuid.uuid4(),
                    organization_id=org.id,
                    created_by=admin.id,
                    user_id=user.id,
                    full_name=name,
                    phone=phone,
                    license_number=license_no,
                    license_type=license_type,
                    license_issue_date=issued,
                    license_expiry=add_years(issued, LICENSE_VALID_YEARS),
                    license_current_status="Active",
                    status=DriverStatus.active,
                )
            )
        db.commit()
        print(f"Created organization '{ORG_NAME}' (slug: {ORG_SLUG}) with {len(staff) + len(driver_users)} users.")


if __name__ == "__main__":
    main()
