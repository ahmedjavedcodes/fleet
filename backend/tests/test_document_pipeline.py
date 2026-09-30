"""Unit tests for the ingestion stages (hybrid-document-rag-pipeline.md §2):
spatial extraction, recursive chunking, cost-bounded table summarization,
hybrid scaling, deterministic ids. No DB, no network."""

import uuid

import pymupdf
import pytest

from app.models.enums import DocumentType
from app.services.document_chunking import CHUNK_OVERLAP, CHUNK_SIZE, build_chunks, recursive_split
from app.services.document_extraction import (
    BODY,
    MAJOR_HEADING,
    SUB_HEADING,
    TITLE,
    Box,
    TableBlock,
    TextBlock,
    Unit,
    assemble_blocks,
    extract_pdf_units,
    extract_text_units,
    is_heading,
    structure_units,
)
from app.services.document_service import DocumentSearchCache, document_id_for
from app.services.rag_inference import hybrid_scale
from app.services.table_summarizer import summarize_tables


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


# ---- §2.3 chunking: small recursive chunks that carry their section heading ----

MANUAL_TEXT = (
    "Standard Tyre Pressure Guidelines Unloaded/Light Cargo: 30 PSI for all four tyres to maintain optimal fuel efficiency "
    "and tread wear. Heavy Cargo/Loaded: The recommended tyre pressure for a loaded Hilux is 35 PSI in the front and 45 PSI "
    "in the rear. Off-Road Conditions: Consult the Maintenance & Spare Parts Agent for temporary deflation parameters based "
    "on terrain."
)
INCIDENT_TEXT = (
    "In the event of an emergency, drivers must first secure the vehicle and contact local emergency services if injuries "
    "are present. Following immediate safety measures, all severe accidents must be reported within 1 hour to the fleet manager."
)


def _text(*texts: str) -> list[Unit]:
    return [Unit("text", 0, float(i), t) for i, t in enumerate(texts)]


def test_chunks_are_small_and_nothing_is_lost() -> None:
    sentences = [f"Sentence number {i} is about brake pad wear on route {i}." for i in range(60)]
    text = " ".join(sentences)
    chunks = recursive_split(text)

    assert len(chunks) > 5 and all(len(c) <= CHUNK_SIZE for c in chunks)
    assert all(s in " ".join(chunks) for s in sentences)  # every sentence survives whole in at least one chunk
    assert all(c in text for c in chunks)  # and each chunk is a contiguous stretch of the original (overlap included)


def test_neighbouring_chunks_overlap_by_about_fifty_characters_from_a_clean_start() -> None:
    text = " ".join(f"Sentence number {i} is about brake pads." for i in range(40))
    chunks = recursive_split(text)

    for previous, current in zip(chunks, chunks[1:], strict=False):
        shared = next(n for n in range(min(len(previous), len(current)), 0, -1) if previous.endswith(current[:n]))
        assert 10 <= shared <= CHUNK_OVERLAP  # a real overlap, never more than configured
        assert current[0].isupper()  # it starts at a sentence, not mid-word


def test_overlap_can_be_switched_off_and_a_short_text_is_one_chunk() -> None:
    text = " ".join(f"Sentence number {i} is about brake pads." for i in range(40))
    flat = recursive_split(text, CHUNK_SIZE, 0)

    assert " ".join(flat) == text  # no repeated text at all
    assert recursive_split("Just one short sentence.") == ["Just one short sentence."]
    assert recursive_split("   ") == []


def test_a_word_longer_than_a_chunk_is_still_cut_to_size() -> None:
    chunks = recursive_split("x" * 1_000)

    assert all(len(c) <= CHUNK_SIZE for c in chunks) and "".join(chunks).count("x") >= 1_000


def test_paragraph_breaks_are_preferred_over_sentence_breaks() -> None:
    first, second = "A" + " word" * 40 + ".", "B" + " word" * 40 + "."
    chunks = recursive_split(first + "\n\n" + second, 300, 0)

    assert chunks == [first, second]


def test_the_manual_is_split_by_section_and_each_chunk_carries_its_heading() -> None:
    chunks = build_chunks(
        _text("1.0 Toyota Hilux Specifications", MANUAL_TEXT, "2.0 Company Incident Protocols", INCIDENT_TEXT), {}
    )

    tyre = [c.text for c in chunks if "PSI" in c.text]
    incident = [c.text for c in chunks if "accidents" in c.text]
    assert tyre and incident
    assert all(t.startswith("1.0 Toyota Hilux Specifications\n") for t in tyre)
    assert all(t.startswith("2.0 Company Incident Protocols\n") for t in incident)
    assert not any("PSI" in c.text and "accidents" in c.text for c in chunks)  # no chunk answers two sections
    assert all(len(c.text) <= CHUNK_SIZE for c in chunks) and all(c.embed_text == c.text for c in chunks)


def test_a_heading_inside_a_paragraph_block_is_split_off_its_first_line() -> None:
    chunks = build_chunks(_text("2.0 Company Incident Protocols\n" + INCIDENT_TEXT), {})

    assert chunks[0].text.startswith("2.0 Company Incident Protocols\nIn the event of an emergency")


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("2.0 Company Incident Protocols", True),
        ("4.0 General Conduct & Compliance", True),
        ("Standard Tyre Pressure Guidelines", True),
        ("Mandatory Incident Reporting Timelines", True),
        ("All severe accidents must be reported within 1 hour to the fleet manager.", False),
        ("Drivers must verify their assignment.", False),
        ("Fleet Operations & Maintenance Manual Page 1 of 2", False),  # running footer
        ("12345", False),
        ("", False),
        ("Note:", False),
    ],
)
def test_what_counts_as_a_section_heading(line, expected) -> None:
    assert is_heading(line) is expected


def test_running_headers_and_footers_are_not_indexed() -> None:
    units = _text("2.0 Company Incident Protocols", INCIDENT_TEXT, "Fleet Operations & Maintenance Manual Page 1 of 2", "Page 2")

    assert not any("Page" in c.text for c in build_chunks(units, {}))


def test_a_document_of_headings_alone_still_yields_something_to_search() -> None:
    assert [c.text for c in build_chunks(_text("Fleet Safety Policy"), {})] == ["Fleet Safety Policy"]


def test_text_without_any_heading_is_chunked_plainly() -> None:
    chunks = build_chunks(_text(INCIDENT_TEXT + " " + INCIDENT_TEXT), {})

    assert len(chunks) >= 2 and all(len(c.text) <= CHUNK_SIZE for c in chunks)


def test_tables_are_single_chunks_embedded_by_summary() -> None:
    units = [Unit("text", 0, 0, "Intro sentence one. Intro sentence two."), Unit("table", 0, 10, "|a|b|", markdown="|a|b|"),
             Unit("text", 0, 20, "Outro.")]
    chunks = build_chunks(units, {1: ("summary of table", "summary of table\n\n|a|b|")})
    table_chunk = next(c for c in chunks if "|a|b|" in c.text)
    assert table_chunk.embed_text == "summary of table"  # embed the summary...
    assert "|a|b|" in table_chunk.text  # ...but keep the exact table for citation


def test_the_section_heading_still_applies_after_a_table() -> None:
    units = [Unit("text", 0, 0, "3.0 Brake Service Schedule"), Unit("text", 0, 1, "Replacement intervals are listed below."),
             Unit("table", 0, 2, "|a|b|", markdown="|a|b|"), Unit("text", 0, 3, "Always torque wheel nuts to 105 Nm.")]
    chunks = build_chunks(units, {})

    assert [c.text for c in chunks][-1] == "3.0 Brake Service Schedule\nAlways torque wheel nuts to 105 Nm."
    assert not any(c.text == "3.0 Brake Service Schedule" for c in chunks)  # no heading-only chunk


# ---- structure: headings from font sizes, wrapped lines back into paragraphs ----


def _line(page: int, y0: float, text: str, size: float = 10.5, height: float = 12.6) -> TextBlock:
    return TextBlock(page, Box(72, y0, 500, y0 + height), text, size=size)


def _manual_blocks() -> list[TextBlock]:
    """The shape of a real manual exported from a word processor: every wrapped line is a block of its own, headings
    differ from body text only by size, a run-in label ends in a colon, the last period of a paragraph can be a
    block by itself, and a footer sits at the bottom of the page."""
    return [
        _line(0, 72, "Fleet Operations & Maintenance\nManual", size=24, height=60),
        _line(0, 134, "Document ID: FOM-2026-V1 | Last Updated: September 2026", size=11),
        _line(0, 192, "1.0 Toyota Hilux Specifications", size=16, height=20),
        _line(0, 233, "To ensure optimal performance, all fleet drivers must adhere to"),
        _line(0, 250, "the manufacturer's specifications for every Hilux."),
        _line(0, 321, "Standard Tyre Pressure Guidelines", size=11),
        _line(0, 342, "Unloaded/Light Cargo:", size=11),
        _line(0, 366, "30 PSI for all four tyres."),
        _line(0, 388, "Heavy Cargo/Loaded:", size=11),
        _line(0, 412, "35 PSI in the front and 45 PSI in the rear"),
        _line(0, 440, "."),
        _line(0, 800, "Fleet Operations & Maintenance Manual\nPage 1 of 2", size=8.5, height=22),
    ]


def test_headings_are_told_from_body_text_by_font_size_and_the_title_is_not_a_section() -> None:
    units = structure_units(assemble_blocks(_manual_blocks(), []))

    assert [u.heading for u in units] == [TITLE, BODY, MAJOR_HEADING, BODY, SUB_HEADING, BODY, BODY]
    assert [" ".join(u.text.split()) for u in units if u.heading in (TITLE, MAJOR_HEADING, SUB_HEADING)] == [
        "Fleet Operations & Maintenance Manual",
        "1.0 Toyota Hilux Specifications",
        "Standard Tyre Pressure Guidelines",
    ]
    assert units[1].text.startswith("Document ID: FOM-2026-V1")  # a metadata line in slightly larger type stays body text


def test_wrapped_lines_become_paragraphs_labels_join_their_text_and_a_lone_period_rejoins_its_sentence() -> None:
    units = structure_units(assemble_blocks(_manual_blocks(), []))

    assert units[3].text == "To ensure optimal performance, all fleet drivers must adhere to the manufacturer's specifications for every Hilux."
    assert units[5].text == "Unloaded/Light Cargo: 30 PSI for all four tyres."  # a label takes the text after it...
    assert units[6].text == "Heavy Cargo/Loaded: 35 PSI in the front and 45 PSI in the rear."  # ...and the gap starts a new paragraph


def test_the_running_footer_is_dropped_and_never_joins_the_paragraph_above_it() -> None:
    units = structure_units(assemble_blocks(_manual_blocks(), []))

    assert not any("Page 1 of 2" in u.text for u in units)
    assert units[-1].text.endswith("45 PSI in the rear.")  # the lone "." rejoined, nothing after it


def test_a_paragraph_break_is_kept_when_the_gap_is_large_and_the_sentence_has_ended() -> None:
    blocks = [_line(0, 100, "First paragraph ends here."), _line(0, 113, "Still the same paragraph."), _line(0, 170, "A new paragraph starts.")]

    assert [u.text for u in structure_units(assemble_blocks(blocks, []))] == [
        "First paragraph ends here. Still the same paragraph.",
        "A new paragraph starts.",
    ]


def test_text_in_a_different_size_is_not_folded_into_the_paragraph() -> None:
    blocks = [_line(0, 100, "Body text that goes on"), _line(0, 113, "a caption in small print", size=7)]

    assert len(structure_units(assemble_blocks(blocks, []))) == 2


def test_without_font_sizes_units_are_left_exactly_as_they_were() -> None:
    units = [Unit("text", 0, 0.0, "2.0 Company Incident Protocols"), Unit("text", 0, 1.0, "Some paragraph.")]

    assert structure_units(units) == units and all(u.heading is None for u in units)


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("30 PSI for all four tyres to maintain", False),  # a wrapped line that happens to start with a number
        ("1 hour to the fleet manager", False),
        ("1. Introduction", True),  # plain Title Case after a number still reads as a heading
        ("Document ID: FOM-2026-V1 | Last Updated: September 2026", False),  # metadata, not a section
        ("Heavy Cargo/Loaded:", False),  # a label
        ("2.0 Company Incident Protocols", True),
        ("3.2.1 Brake Service Intervals", True),
    ],
)
def test_what_reads_as_a_heading_and_what_does_not(line, expected) -> None:
    assert is_heading(line) is expected


def _manual_pdf() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    rows = [
        (72, "Fleet Operations Manual", 24), (130, "1.0 Incident Protocols", 16),
        (170, "All severe accidents must be reported", 10.5), (186, "within 1 hour to the fleet manager.", 10.5),
        (240, "Mandatory Reporting Timelines", 11), (262, "Minor incidents must be filed within 24 hours.", 10.5),
        (800, "Fleet Operations Manual Page 1 of 1", 8.5),
    ]
    for y, text, size in rows:  # one insert per line: every line becomes a block of its own, like the real manual
        page.insert_text((72, y), text, fontsize=size)
    data = doc.tobytes()
    doc.close()
    return data


def test_a_real_pdf_with_one_block_per_line_is_chunked_by_section_with_breadcrumbs() -> None:
    chunks = build_chunks(extract_pdf_units(_manual_pdf()), {})

    assert [c.text for c in chunks] == [
        "Fleet Operations Manual",
        "1.0 Incident Protocols\nAll severe accidents must be reported within 1 hour to the fleet manager.",
        "1.0 Incident Protocols › Mandatory Reporting Timelines\nMinor incidents must be filed within 24 hours.",
    ]


# ---- chunking with explicit heading levels ----


def _sized(kind_level: int | None, text: str, y: float = 0.0) -> Unit:
    return Unit("text", 0, y, text, heading=kind_level)


def test_a_sub_heading_is_shown_under_its_major_heading_and_a_new_major_heading_resets_it() -> None:
    units = [
        _sized(MAJOR_HEADING, "2.0 Company Incident Protocols"), _sized(BODY, "Driver safety is the highest priority."),
        _sized(SUB_HEADING, "Mandatory Incident Reporting Timelines"), _sized(BODY, "Report severe accidents within 1 hour."),
        _sized(MAJOR_HEADING, "3.0 Fuel Card Usage"), _sized(BODY, "Cards are issued per vehicle."),
    ]

    assert [c.text.split("\n")[0] for c in build_chunks(units, {})] == [
        "2.0 Company Incident Protocols",
        "2.0 Company Incident Protocols › Mandatory Incident Reporting Timelines",
        "3.0 Fuel Card Usage",
    ]


def test_an_overlong_breadcrumb_falls_back_to_the_innermost_heading() -> None:
    major, sub = "9.0 " + "Very Long Major Heading " * 3, "Short Sub Heading"
    units = [_sized(MAJOR_HEADING, major.strip()), _sized(SUB_HEADING, sub), _sized(BODY, "Body text here.")]

    (chunk,) = build_chunks(units, {})

    assert chunk.text == f"{sub}\nBody text here."


def test_a_title_sized_unit_is_content_not_a_section() -> None:
    chunks = build_chunks([_sized(TITLE, "Fleet Manual"), _sized(BODY, "Intro text."), _sized(MAJOR_HEADING, "1.0 Scope"), _sized(BODY, "Scope text.")], {})

    assert [c.text for c in chunks] == ["Fleet Manual\n\nIntro text.", "1.0 Scope\nScope text."]


def test_a_table_without_a_summary_keeps_the_text_folded_into_it_and_its_section() -> None:
    units = [
        _sized(MAJOR_HEADING, "3.0 Fuel Card Usage"),
        Unit("table", 0, 5, "|a|b|", context=". Any attempt to use the card elsewhere will be declined.", markdown="|a|b|"),
    ]

    (chunk,) = build_chunks(units, {})

    assert chunk.text == "3.0 Fuel Card Usage\nAny attempt to use the card elsewhere will be declined.\n\n|a|b|"
    assert chunk.embed_text == chunk.text  # so a search for that sentence finds the table


def test_a_summarised_table_is_embedded_by_its_summary_with_its_section() -> None:
    units = [_sized(MAJOR_HEADING, "3.0 Fuel Card Usage"), Unit("table", 0, 5, "|a|b|", context="Intro.", markdown="|a|b|")]

    (chunk,) = build_chunks(units, {1: ("Which fuel each vehicle takes.", "Which fuel each vehicle takes.\n\n|a|b|")})

    assert chunk.embed_text == "3.0 Fuel Card Usage\nWhich fuel each vehicle takes."
    assert "|a|b|" in chunk.text


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
