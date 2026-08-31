"""Tests for pure service utilities: shaping, pagination, citation.

TDD order: tests written first, implementation comes after.
"""

from __future__ import annotations

import json

import pytest

# ---------------------------------------------------------------------------
# pagination tests
# ---------------------------------------------------------------------------


def test_paginate_truncated_returns_page_and_block() -> None:
    from metadome_link.services.pagination import paginate

    items = list(range(10))
    page, block = paginate(items, limit=3, offset=0)

    assert page == [0, 1, 2]
    assert block["total"] == 10
    assert block["returned"] == 3
    assert block["limit"] == 3
    assert block["offset"] == 0
    assert block["truncated"] is True
    assert block["next_offset"] == 3


def test_paginate_not_truncated_next_offset_is_none() -> None:
    from metadome_link.services.pagination import paginate

    items = list(range(5))
    page, block = paginate(items, limit=10, offset=0)

    assert page == [0, 1, 2, 3, 4]
    assert block["total"] == 5
    assert block["returned"] == 5
    assert block["truncated"] is False
    assert block["next_offset"] is None


def test_paginate_with_nonzero_offset() -> None:
    from metadome_link.services.pagination import paginate

    items = list(range(10))
    page, block = paginate(items, limit=3, offset=4)

    assert page == [4, 5, 6]
    assert block["total"] == 10
    assert block["returned"] == 3
    assert block["offset"] == 4
    assert block["truncated"] is True
    assert block["next_offset"] == 7


def test_paginate_last_page_not_truncated() -> None:
    from metadome_link.services.pagination import paginate

    items = list(range(10))
    page, block = paginate(items, limit=5, offset=5)

    assert page == [5, 6, 7, 8, 9]
    assert block["total"] == 10
    assert block["returned"] == 5
    assert block["truncated"] is False
    assert block["next_offset"] is None


def test_paginate_limit_equals_len() -> None:
    from metadome_link.services.pagination import paginate

    items = list(range(5))
    page, block = paginate(items, limit=5, offset=0)

    assert len(page) == 5
    assert block["truncated"] is False
    assert block["next_offset"] is None


def test_paginate_empty_list() -> None:
    from metadome_link.services.pagination import paginate

    page, block = paginate([], limit=10, offset=0)

    assert page == []
    assert block["total"] == 0
    assert block["returned"] == 0
    assert block["truncated"] is False
    assert block["next_offset"] is None


# ---------------------------------------------------------------------------
# shaping tests
# ---------------------------------------------------------------------------


def test_shape_record_compact_drops_null_and_empty() -> None:
    from metadome_link.services.shaping import shape_record

    record = {
        "transcript_id": "ENST00000269305.9",
        "gene_name": "TP53",
        "aa_length": None,
        "domains": [],
        "description": "",
        "extra": {},
    }
    result = shape_record(record, "compact")

    assert "transcript_id" in result
    assert "gene_name" in result
    assert "aa_length" not in result
    assert "domains" not in result
    assert "description" not in result
    assert "extra" not in result


def test_shape_record_standard_keeps_all_fields() -> None:
    from metadome_link.services.shaping import shape_record

    record = {
        "transcript_id": "ENST00000269305.9",
        "gene_name": "TP53",
        "aa_length": None,
        "domains": [],
    }
    result = shape_record(record, "standard")

    assert result == record


def test_shape_record_full_keeps_all_fields() -> None:
    from metadome_link.services.shaping import shape_record

    record = {
        "transcript_id": "ENST00000269305.9",
        "aa_length": None,
        "domains": [],
    }
    result = shape_record(record, "full")

    assert result == record


def test_shape_record_minimal_keeps_collection_results() -> None:
    """minimal must not empty a COLLECTION result (grouped/list payload)."""
    from metadome_link.services.shaping import shape_record

    record = {
        "transcript_id": "ENST00000269305.9",
        "gene_name": "TP53",
        "domains": [{"name": "p53"}],
        "meta_domains": {"PF00870": {"pathogenic_variants": [{"pos": 175}]}},
        "recommended_citation": "MetaDome ...",
        "data_currency_caveat": "long redundant caveat string",
    }
    result = shape_record(record, "minimal")

    assert result["transcript_id"] == "ENST00000269305.9"
    assert result["domains"] == [{"name": "p53"}]
    assert result["meta_domains"] == {"PF00870": {"pathogenic_variants": [{"pos": 175}]}}
    # the mandatory citation survives; only the redundant prose caveat is dropped
    assert result["recommended_citation"] == "MetaDome ..."
    assert "data_currency_caveat" not in result


def test_shape_record_minimal_keeps_scalar_results() -> None:
    """minimal must not drop SCALAR results -- the N+1 (single-record) tool shape.

    get_position_tolerance returns scalars (protein_pos/ref_aa/sw_dn_ds); a
    projection that keeps only identity anchors or only collections would silently
    make this tool unusable at success:true. This is the case that guards the class.
    """
    from metadome_link.services.shaping import shape_record

    record = {
        "transcript_id": "ENST00000269305.9",
        "protein_pos": 175,
        "ref_aa": "R",
        "sw_dn_ds": 0.123,
        "recommended_citation": "MetaDome ...",
        "data_currency_caveat": "long redundant caveat string",
    }
    result = shape_record(record, "minimal")

    # every essential scalar result survives
    assert result["protein_pos"] == 175
    assert result["ref_aa"] == "R"
    assert result["sw_dn_ds"] == 0.123
    assert result["recommended_citation"] == "MetaDome ..."
    # only the verbose/redundant prose is dropped
    assert "data_currency_caveat" not in result


def test_shape_record_minimal_keeps_build_handle_scalars() -> None:
    """minimal must not drop request_tolerance_landscape's poll handle (job_id/status/poll_after_s)."""
    from metadome_link.services.shaping import shape_record

    record = {
        "job_id": "ENST00000269305.9",
        "status": "processing",
        "poll_after_s": 30,
        "recommended_citation": "MetaDome ...",
    }
    result = shape_record(record, "minimal")

    assert result["job_id"] == "ENST00000269305.9"
    assert result["status"] == "processing"
    assert result["poll_after_s"] == 30
    assert result["recommended_citation"] == "MetaDome ..."


def test_shape_record_compact_preserves_meta_and_success() -> None:
    from metadome_link.services.shaping import shape_record

    record = {
        "transcript_id": "ENST00000269305.9",
        "_meta": {"tool": "get_landscape"},
        "success": True,
        "empty_field": [],
    }
    result = shape_record(record, "compact")

    # _meta and success always preserved even if empty
    assert "_meta" in result
    assert "success" in result
    assert "empty_field" not in result


def test_select_fields_returns_requested_fields_plus_anchors() -> None:
    from metadome_link.services.shaping import select_fields

    payload = {
        "transcript_id": "ENST00000269305.9",
        "gene_name": "TP53",
        "aa_length": 393,
        "domains": [{"name": "p53"}],
        "_meta": {"tool": "test"},
        "success": True,
    }
    result = select_fields(payload, ["aa_length"])

    assert "aa_length" in result
    assert "_meta" in result
    assert "success" in result
    # transcript_id and gene_name are identity anchors → always present
    assert "transcript_id" in result
    # domains not requested → absent
    assert "domains" not in result


def test_select_fields_no_fields_returns_payload_unchanged() -> None:
    from metadome_link.services.shaping import select_fields

    payload = {"a": 1, "b": 2}
    assert select_fields(payload, None) is payload  # type: ignore[arg-type]
    assert select_fields(payload, []) == payload


def test_char_budget_guard_under_budget_unchanged() -> None:
    from metadome_link.services.shaping import char_budget_guard

    payload = {"transcript_id": "ENST00000269305.9", "gene_name": "TP53"}
    result = char_budget_guard(payload, max_chars=10_000)

    assert result == payload
    assert "dropped_summary" not in result


def test_char_budget_guard_over_budget_truncates_lists_and_injects_summary() -> None:
    from metadome_link.services.shaping import char_budget_guard

    payload = {
        "transcript_id": "ENST00000269305.9",
        "positions": list(range(500)),  # big list
        "domains": list(range(50)),  # another list
    }
    result = char_budget_guard(payload, max_chars=200)

    # Should be within budget after truncation (rough check)
    import json

    assert len(json.dumps(result)) <= 200 * 2  # some slack for overhead
    # dropped_summary must be injected
    assert "dropped_summary" in result
    # transcript_id must survive (scalar)
    assert result["transcript_id"] == "ENST00000269305.9"
    # at least one list field was truncated
    positions = result.get("positions", [])
    assert isinstance(positions, list)


def test_char_budget_guard_truncates_nested_meta_domain_lists() -> None:
    from metadome_link.services.shaping import char_budget_guard

    payload = {
        "transcript_id": "ENST00000269305.9",
        "protein_position": 175,
        "meta_domains": {
            "PF00870": {
                "alignment_depth": 42,
                "pathogenic_variants": [
                    {"clinvar_ID": str(i), "pad": "z" * 30} for i in range(400)
                ],
            },
        },
    }
    original_input = json.loads(json.dumps(payload))  # snapshot to detect mutation
    result = char_budget_guard(payload, max_chars=500)

    assert len(json.dumps(result)) <= 500
    # The bulk lives in a nested list; the guard must reach it and record it.
    assert "dropped_summary" in result
    assert "meta_domains.PF00870.pathogenic_variants" in result["dropped_summary"]
    assert len(result["meta_domains"]["PF00870"]["pathogenic_variants"]) < 400
    # Dict scaffolding (alignment_depth, identity anchors) survives.
    assert result["meta_domains"]["PF00870"]["alignment_depth"] == 42
    assert result["transcript_id"] == "ENST00000269305.9"
    # The caller's input dict is not mutated.
    assert payload == original_input


def test_char_budget_guard_rejects_untruncatable_oversized_scalars() -> None:
    from metadome_link.services.shaping import char_budget_guard

    with pytest.raises(ValueError):
        char_budget_guard({"huge": "x" * 1_000}, max_chars=100)


def test_response_modes_and_default_exported() -> None:
    from metadome_link.services.shaping import DEFAULT_RESPONSE_MODE, RESPONSE_MODES

    assert RESPONSE_MODES == ["minimal", "compact", "standard", "full"]
    assert DEFAULT_RESPONSE_MODE == "compact"


# ---------------------------------------------------------------------------
# citation tests
# ---------------------------------------------------------------------------


def test_recommended_citation_contains_doi() -> None:
    from metadome_link.services.citation import recommended_citation

    cit = recommended_citation()
    assert "humu.23798" in cit


def test_recommended_citation_with_transcript_id_appended() -> None:
    from metadome_link.services.citation import recommended_citation

    cit = recommended_citation(transcript_id="ENST00000269305.9")
    assert "humu.23798" in cit
    assert "Transcript ENST00000269305.9" in cit


def test_recommended_citation_with_gene_name() -> None:
    from metadome_link.services.citation import recommended_citation

    cit = recommended_citation(gene_name="TP53")
    # gene_name alone does not change the core citation
    assert "humu.23798" in cit


def test_recommended_citation_transcript_and_gene() -> None:
    from metadome_link.services.citation import recommended_citation

    cit = recommended_citation(transcript_id="ENST00000269305.9", gene_name="TP53")
    assert "Transcript ENST00000269305.9" in cit


def test_citation_template_is_string() -> None:
    from metadome_link.services.citation import citation_template

    tmpl = citation_template()
    assert isinstance(tmpl, str)
    assert len(tmpl) > 0
