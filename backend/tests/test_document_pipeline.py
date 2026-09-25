"""Unit tests for the ingestion stages (hybrid-document-rag-pipeline.md §2):
spatial extraction, semantic chunking, cost-bounded table summarization,
hybrid scaling, deterministic ids. No DB, no network."""

import uuid

import pymupdf
import pytest

from app.models.enums import DocumentType
from app.services.document_chunking import build_chunks, semantic_split, split_sentences
from app.services.document_extraction import Box, TableBlock, TextBlock, Unit, assemble_blocks, extract_pdf_units, extract_text_units
from app.services.document_service import DocumentSearchCache, document_id_for
from app.services.rag_inference import hybrid_scale
from app.services.table_summarizer import summarize_tables
from tests.fake_rag_inference import FakeRagInference


def _pdf_with_table() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Brake Service Schedule", fontsize=14)
    page.insert_text((72, 105), "The table below lists replacement intervals.", fontsize=10)
    x0, y0, cw, rh = 72, 130, 150, 20
    for r, row in enumerate([["Part", "Interval (km)"], ["Brake pads", "40,000"], ["Brake fluid", "60,000"]]):
        for c, cell in enumerate(row):
            page.draw_rect(pymupdf.Rect(x0 + c * cw, y0 + r * rh, x0 + (c + 1) * cw, y0 + (r + 1) * rh))
            page.insert_text((x0 + c * cw + 4, y0 + r * rh + 14), cell, fontsize=10)
    page.insert_text((72, 300), "Always torque wheel nuts to 105 Nm after pad replacement.", fontsize=10)
    data = doc.tobytes()
    doc.close()
    return data


# ---- §2.1 spatial sequencing ----


def test_table_absorbs_the_heading_within_60pt_above_it() -> None:
    text = [
        TextBlock(0, Box(72, 40, 400, 55), "Unrelated intro far above."),  # 75pt above: stays separate
        TextBlock(0, Box(72, 90, 400, 105), "Replacement intervals:"),  # 25pt above: table context
        TextBlock(0, Box(72, 120, 400, 180), "Part Interval Brake pads 40,000"),  # overlaps table: duplicate cell text
        TextBlock(0, Box(72, 200, 400, 215), "Torque wheel nuts after replacement."),
    ]
    table = TableBlock(0, Box(72, 115, 400, 185), "|Part|Interval|\n|---|---|\n|Brake pads|40,000|")

    units = assemble_blocks(text, [table])

    assert [u.kind for u in units] == ["text", "table", "text"]
    assert units[1].context == "Replacement intervals:"
    assert "Brake pads 40,000" not in " ".join(u.text for u in units if u.kind == "text")  # deduplicated


def test_units_are_ordered_by_page_then_vertical_position() -> None:
    blocks = [
        TextBlock(1, Box(0, 10, 100, 20), "page two top"),
        TextBlock(0, Box(0, 500, 100, 510), "page one bottom"),
        TextBlock(0, Box(0, 10, 100, 20), "page one top"),
    ]
    assert [u.text for u in assemble_blocks(blocks, [])] == ["page one top", "page one bottom", "page two top"]


def test_real_pdf_extraction_keeps_table_intact_and_in_reading_order() -> None:
    units = extract_pdf_units(_pdf_with_table())
    kinds = [u.kind for u in units]
    table = units[kinds.index("table")]

    assert "|Brake pads|40,000|" in table.markdown
    assert "replacement intervals" in table.context
    assert kinds.index("table") < max(i for i, u in enumerate(units) if "torque" in u.text.lower())


def test_plain_text_splits_into_paragraphs() -> None:
    units = extract_text_units("First paragraph.\n\nSecond paragraph.\r\n\r\n\n")
    assert [u.text for u in units] == ["First paragraph.", "Second paragraph."]


# ---- §2.3 semantic chunking ----


def test_semantic_split_breaks_at_the_topic_shift() -> None:
    sentences = [
        "Brake pads wear out.", "Brake pads need inspection.", "Brake pads squeal when worn.",
        "Fuel receipts must be filed.", "Fuel receipts need a date.",
    ]
    chunks = semantic_split(sentences, lambda s: FakeRagInference().embed_dense(s, "passage"), percentile=75)
    assert any("Brake" in c and "Fuel" not in c for c in chunks)
    assert any("Fuel" in c and "Brake" not in c for c in chunks)


def test_semantic_split_respects_max_chars() -> None:
    sentences = [f"Sentence number {i} about brakes." for i in range(40)]
    chunks = semantic_split(sentences, lambda s: FakeRagInference().embed_dense(s, "passage"), max_chars=200)
    assert all(len(c) <= 200 for c in chunks)
    assert " ".join(chunks).count("Sentence number") == 40  # nothing dropped


def test_tables_are_single_chunks_embedded_by_summary() -> None:
    units = [Unit("text", 0, 0, "Intro sentence one. Intro sentence two."), Unit("table", 0, 10, "|a|b|", markdown="|a|b|"),
             Unit("text", 0, 20, "Outro.")]
    chunks = build_chunks(units, {1: ("summary of table", "summary of table\n\n|a|b|")},
                          lambda s: FakeRagInference().embed_dense(s, "passage"))
    table_chunk = next(c for c in chunks if "|a|b|" in c.text)
    assert table_chunk.embed_text == "summary of table"  # embed the summary...
    assert "|a|b|" in table_chunk.text  # ...but keep the exact table for citation


def test_split_sentences() -> None:
    assert split_sentences("Pads wear. Check at 10,000 km!  Replace at 3 mm?") == ["Pads wear.", "Check at 10,000 km!", "Replace at 3 mm?"]


# ---- §2.2 cost-bounded summarization ----


def test_summaries_capped_at_max_tables_rest_fall_back_to_markdown() -> None:
    tables = [(i, f"|t{i}|", "") for i in range(17)]
    calls = []
    outcome = summarize_tables(tables, lambda p: calls.append(p) or "a summary", max_tables=15, sleep=lambda s: None)
    assert outcome.summarized == 15 and len(calls) == 15
    assert outcome.texts[16] == ("|t16|", "|t16|")
    assert outcome.failures == []


def test_summarization_retries_with_backoff_then_falls_back_and_records_failure() -> None:
    sleeps = []

    def _down(prompt):
        raise ConnectionError("groq down")

    outcome = summarize_tables([(3, "|x|", "Context")], _down, max_tables=15, sleep=sleeps.append)
    assert sleeps == [1.0, 2.0]  # exponential backoff between the 3 attempts
    assert outcome.texts[3] == ("Context\n\n|x|", "Context\n\n|x|")
    assert outcome.failures[0]["attempts"] == 3 and "groq down" in outcome.failures[0]["error"]


def test_transient_failure_then_success() -> None:
    replies = iter([ConnectionError("blip"), "recovered summary"])

    def _flaky(prompt):
        value = next(replies)
        if isinstance(value, Exception):
            raise value
        return value

    outcome = summarize_tables([(0, "|x|", "")], _flaky, max_tables=15, sleep=lambda s: None)
    assert outcome.summarized == 1 and outcome.texts[0][0] == "recovered summary"


def test_no_llm_configured_means_markdown_without_failures() -> None:
    outcome = summarize_tables([(0, "|x|", "")], None, max_tables=15)
    assert outcome.summarized == 0 and outcome.failures == []


# ---- ids, hybrid scaling, cache ----


def test_document_id_is_deterministic_and_tenant_scoped() -> None:
    org_a, org_b = uuid.uuid4(), uuid.uuid4()
    assert document_id_for(org_a, "manual.pdf", DocumentType.manual) == document_id_for(org_a, "manual.pdf", DocumentType.manual)
    # The spec's hash(filename + type) would collide across tenants.
    assert document_id_for(org_a, "manual.pdf", DocumentType.manual) != document_id_for(org_b, "manual.pdf", DocumentType.manual)
    assert document_id_for(org_a, "manual.pdf", DocumentType.manual) != document_id_for(org_a, "manual.pdf", DocumentType.policy)


def test_hybrid_scale_is_a_convex_combination() -> None:
    dense, sparse = hybrid_scale([1.0, 2.0], {"indices": [5], "values": [4.0]}, 0.25)
    assert dense == [0.25, 0.5] and sparse == {"indices": [5], "values": [3.0]}
    with pytest.raises(ValueError):
        hybrid_scale([1.0], {"indices": [], "values": []}, 1.5)


def test_cache_is_keyed_by_org_and_role_scope() -> None:
    cache = DocumentSearchCache()
    vec = [1.0, 0.0]
    cache.put(("org-a", ("manual", "supplier_invoice")), vec, [{"text": "invoice total PKR 50,000"}])
    assert cache.get(("org-a", ("manual", "supplier_invoice")), [0.99, 0.01]) is not None  # > 0.95 similar
    assert cache.get(("org-a", ("manual", "policy")), vec) is None  # a driver's scope never sees it
    assert cache.get(("org-b", ("manual", "supplier_invoice")), vec) is None
    assert cache.get(("org-a", ("manual", "supplier_invoice")), [0.0, 1.0]) is None  # dissimilar query
    cache.invalidate_org("org-a")
    assert cache.get(("org-a", ("manual", "supplier_invoice")), vec) is None
