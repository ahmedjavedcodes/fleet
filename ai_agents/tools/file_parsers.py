"""File-parsing agent tools.

Fleet data arrives only via uploaded documents (CLAUDE.md: no live
telemetry). These tools turn driver trip sheets, supplier invoices, and
onboarding documents (licenses, vehicle registration cards, supplier docs)
into structured records the agent can reason over.
"""

from __future__ import annotations

import base64
import csv
from io import StringIO
from typing import Any

from core.llm_config import LLMProvider, get_chat_model
from tools.schemas import LicenseExtraction, SupplierDocExtraction, VehicleDocExtraction

_SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/png"}


def parse_trip_sheet_csv(csv_text: str) -> list[dict[str, Any]]:
    """Parse a driver trip sheet CSV into a list of row dicts."""
    reader = csv.DictReader(StringIO(csv_text))
    return list(reader)


def parse_supplier_invoice_pdf(pdf_bytes: bytes) -> dict[str, Any]:
    """Extract structured fields from a supplier invoice PDF.

    Placeholder pending selection of a PDF-extraction library (e.g. pypdf,
    pdfplumber); wired up alongside the parts-inventory feature.
    """
    raise NotImplementedError("PDF invoice parsing not yet implemented")


class UnsupportedImageTypeError(Exception):
    """Raised when an onboarding upload isn't JPEG/PNG.

    Fleet Registry Agent spec: input images are JPEG/PNG only (one image per
    document, no PDF/HEIC/multi-page) -- see fleet-registry-agent.md,
    Constraints and the "unsupported file type" edge case.
    """


class ExtractionFailedError(Exception):
    """Raised when the vision model can't confidently read the document.

    Per fleet-registry-agent.md's "Vision extraction can't parse the image"
    edge case: the caller halts the onboarding workflow and asks the user
    for a clearer photo, rather than submitting blank/guessed fields.
    """


def _vision_message(image_bytes: bytes, mime_type: str, instruction: str) -> list[dict[str, Any]]:
    if mime_type not in _SUPPORTED_IMAGE_TYPES:
        raise UnsupportedImageTypeError(f"Unsupported image type {mime_type!r}; only JPEG/PNG are accepted.")

    encoded = base64.b64encode(image_bytes).decode("ascii")
    return [
        {"type": "text", "text": instruction},
        {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded}"}},
    ]


def _extract(image_bytes: bytes, mime_type: str, instruction: str, schema: type, *, document_label: str):
    from langchain_core.messages import HumanMessage

    # Validate the image type before touching the LLM client -- an
    # unsupported upload must never cost a model call.
    content = _vision_message(image_bytes, mime_type, instruction)
    message = HumanMessage(content=content)
    model = get_chat_model(LLMProvider.GROQ).with_structured_output(schema)

    try:
        result = model.invoke([message])
    except Exception as exc:  # noqa: BLE001 -- any provider/parsing failure is a read failure here
        raise ExtractionFailedError(f"Could not read the {document_label}: {exc}") from exc

    return result


def extract_license_data(image_bytes: bytes, mime_type: str = "image/jpeg") -> LicenseExtraction:
    """Parse a photographed driver's license via the Groq vision model.

    Output schema: first_name, last_name, license_number, phone_number,
    expiration_date. Any field the model can't read is left None -- callers
    (the LicenseInspectorSubAgent / onboarding graph) are responsible for
    treating a None required field as an extraction failure, not a valid
    empty value.
    """
    instruction = (
        "Read this driver's license photo and extract: first name, last name, "
        "license number, phone number, and expiration date (as YYYY-MM-DD). "
        "Leave any field you cannot clearly read as null -- never guess."
    )
    return _extract(image_bytes, mime_type, instruction, LicenseExtraction, document_label="driver's license")


def extract_vehicle_doc(image_bytes: bytes, mime_type: str = "image/jpeg") -> VehicleDocExtraction:
    """Parse a photographed vehicle registration card or VIN plate.

    Output schema: plate_number, make, model, year, vin, initial_odometer.
    Fuel type is deliberately not part of this schema -- registration
    documents don't state it, so the graph must ask the user for it before
    calling create_vehicle_tool (fleet-registry-agent.md, FR 8 / AC 5).
    """
    instruction = (
        "Read this vehicle registration card or VIN plate photo and extract: "
        "plate number, make, model, year, VIN, and the odometer reading if "
        "shown. Leave any field you cannot clearly read as null -- never guess."
    )
    return _extract(image_bytes, mime_type, instruction, VehicleDocExtraction, document_label="vehicle document")


def extract_supplier_doc(image_bytes: bytes, mime_type: str = "image/jpeg") -> SupplierDocExtraction:
    """Parse a photographed supplier invoice or registration document.

    Output schema is deliberately narrowed to the fields the backend's
    SupplierCreate schema accepts (name, contact_email, phone) -- other
    extractable text (address, tax/registration ID) is not part of this
    schema and must not be submitted, per fleet-registry-agent.md FR 4.
    """
    instruction = (
        "Read this supplier invoice or registration document and extract: "
        "the supplier's business name, contact email, and phone number. "
        "Leave any field you cannot clearly read as null -- never guess."
    )
    return _extract(image_bytes, mime_type, instruction, SupplierDocExtraction, document_label="supplier document")
