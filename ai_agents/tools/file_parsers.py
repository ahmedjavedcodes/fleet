"""File-parsing agent tools.

Fleet data arrives only via uploaded documents (CLAUDE.md: no live
telemetry). These tools turn driver trip sheets and supplier invoices into
structured records the agent can reason over.
"""

from __future__ import annotations

import csv
from io import StringIO
from typing import Any


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
