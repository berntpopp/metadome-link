"""Focused regressions for the final MetaDome schema and discovery review."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import jsonschema
import pytest
from fastmcp import Client

from metadome_link.mcp import schemas
from metadome_link.mcp.schema_defs import NEXT_COMMAND

_TID = "ENST00000269305.9"
_SCHEMAS: dict[str, dict[str, Any]] = {
    "get_server_capabilities": schemas.GET_SERVER_CAPABILITIES_SCHEMA,
    "get_diagnostics": schemas.GET_DIAGNOSTICS_SCHEMA,
    "resolve_transcript": schemas.RESOLVE_TRANSCRIPT_SCHEMA,
    "request_tolerance_landscape": schemas.REQUEST_TOLERANCE_LANDSCAPE_SCHEMA,
    "get_tolerance_landscape": schemas.GET_TOLERANCE_LANDSCAPE_SCHEMA,
    "get_position_tolerance": schemas.GET_POSITION_TOLERANCE_SCHEMA,
    "get_variant_counts": schemas.GET_VARIANT_COUNTS_SCHEMA,
    "compare_positions": schemas.COMPARE_POSITIONS_SCHEMA,
    "get_protein_domains": schemas.GET_PROTEIN_DOMAINS_SCHEMA,
    "get_meta_domain": schemas.GET_META_DOMAIN_SCHEMA,
    "summarize_intolerant_regions": schemas.SUMMARIZE_INTOLERANT_REGIONS_SCHEMA,
}
_SUCCESS_ARGS: dict[str, dict[str, Any]] = {
    "get_server_capabilities": {},
    "get_diagnostics": {},
    "resolve_transcript": {"query": "TP53"},
    "request_tolerance_landscape": {"transcript_id": _TID},
    "get_tolerance_landscape": {"transcript_id": _TID},
    "get_position_tolerance": {"transcript_id": _TID, "position": 175},
    "get_variant_counts": {"transcript_id": _TID, "position": 35},
    "compare_positions": {"transcript_id": _TID, "positions": [35, 175]},
    "get_protein_domains": {"transcript_id": _TID},
    "get_meta_domain": {"transcript_id": _TID, "position": 175},
    "summarize_intolerant_regions": {"transcript_id": _TID},
}
_ERROR_FIELDS = {
    "error_code": "invalid_input",
    "message": "invalid input",
    "retryable": False,
    "recovery_action": "reformulate_input",
}
_PRIMARY_DATA_FIELD = {
    "get_server_capabilities": "server",
    "get_diagnostics": "cache_stats",
    "resolve_transcript": "resolved_from",
    "request_tolerance_landscape": "job_id",
    "get_tolerance_landscape": "pagination",
    "get_position_tolerance": "variant_evidence",
    "get_variant_counts": "positions",
    "compare_positions": "comparison",
    "get_protein_domains": "domains",
    "get_meta_domain": "meta_domains",
    "summarize_intolerant_regions": "threshold",
}

_READ_ONLY_ARGS = {
    name: args for name, args in _SUCCESS_ARGS.items() if name != "request_tolerance_landscape"
}


def test_next_command_arguments_are_recursive_and_closed() -> None:
    """Command arguments accept real nested selectors but reject injected fields."""
    command = {
        "tool": "get_meta_domain",
        "arguments": {
            "transcript_id": _TID,
            "position": 175,
            "domains": {"PF00870": [81]},
            "limit": 100,
            "offset": 0,
        },
    }
    jsonschema.validate(command, NEXT_COMMAND)

    injected = deepcopy(command)
    injected["arguments"]["unexpected_nested"] = {"instruction": "submit"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(injected, NEXT_COMMAND)


async def _success(facade: Any, call_tool: Any, tool_name: str) -> dict[str, Any]:
    output = await call_tool(
        facade,
        tool_name,
        {**_SUCCESS_ARGS[tool_name], "response_mode": "standard"},
    )
    assert output["success"] is True
    jsonschema.validate(output, _SCHEMAS[tool_name])
    return output


@pytest.mark.parametrize("response_mode", ["minimal", "compact", "standard", "full"])
@pytest.mark.parametrize(("tool_name", "arguments"), _READ_ONLY_ARGS.items())
async def test_read_only_tools_never_submit_a_landscape_build(
    tool_name: str,
    arguments: dict[str, Any],
    response_mode: str,
    facade: Any,
    call_tool: Any,
    mocked_metadome: Any,
) -> None:
    """A cache miss may poll/fetch, but only the explicit request tool may submit."""
    submit = next(
        route for route in mocked_metadome.routes if "/submit_visualization/" in str(route.pattern)
    )
    output = await call_tool(
        facade,
        tool_name,
        {**arguments, "response_mode": response_mode},
    )
    assert output["success"] is True
    assert submit.call_count == 0


@pytest.mark.parametrize("tool_name", _SCHEMAS)
async def test_success_branch_requires_tool_data(
    tool_name: str, facade: Any, call_tool: Any
) -> None:
    """A valid canonical meta block cannot make a data-free success valid."""
    output = await _success(facade, call_tool, tool_name)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            {"success": True, "_meta": output["_meta"]},
            _SCHEMAS[tool_name],
        )
    isolated = deepcopy(output)
    isolated.pop(_PRIMARY_DATA_FIELD[tool_name])
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(isolated, _SCHEMAS[tool_name])


@pytest.mark.parametrize("tool_name", _SCHEMAS)
async def test_success_branch_forbids_error_fields(
    tool_name: str, facade: Any, call_tool: Any
) -> None:
    """A complete success cannot also advertise an error contract."""
    output = await _success(facade, call_tool, tool_name)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**output, **_ERROR_FIELDS}, _SCHEMAS[tool_name])


@pytest.mark.parametrize("tool_name", _SCHEMAS)
async def test_error_branch_forbids_success_data(
    tool_name: str, facade: Any, call_tool: Any
) -> None:
    """A complete canonical error cannot carry any tool success-data field."""
    output = await _success(facade, call_tool, tool_name)
    data_key = _PRIMARY_DATA_FIELD[tool_name]
    error = {
        "success": False,
        "_meta": output["_meta"],
        **_ERROR_FIELDS,
        data_key: output[data_key],
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(error, _SCHEMAS[tool_name])


async def test_nested_records_are_required_typed_and_closed(facade: Any, call_tool: Any) -> None:
    """Each named nested contract rejects one isolated malformed field."""
    landscape = await _success(facade, call_tool, "get_tolerance_landscape")
    domains = await _success(facade, call_tool, "get_protein_domains")
    position = await _success(facade, call_tool, "get_position_tolerance")
    meta_domain = await _success(facade, call_tool, "get_meta_domain")

    mutations: list[tuple[dict[str, Any], dict[str, Any]]] = []
    bad = deepcopy(domains)
    bad["domains"][0] = {}
    mutations.append((bad, schemas.GET_PROTEIN_DOMAINS_SCHEMA))
    bad = deepcopy(landscape)
    bad["positional_annotation"][0] = {}
    mutations.append((bad, schemas.GET_TOLERANCE_LANDSCAPE_SCHEMA))
    bad = deepcopy(landscape)
    bad["pagination"]["truncated"] = 1
    mutations.append((bad, schemas.GET_TOLERANCE_LANDSCAPE_SCHEMA))
    bad = deepcopy(position)
    bad["variant_evidence"] = {}
    mutations.append((bad, schemas.GET_POSITION_TOLERANCE_SCHEMA))
    bad = deepcopy(position)
    membership = next(iter(bad["domains"].values()))
    membership["unknown"] = True
    mutations.append((bad, schemas.GET_POSITION_TOLERANCE_SCHEMA))
    bad = deepcopy(meta_domain)
    block = next(iter(bad["meta_domains"].values()))
    block["normal_variants"][0] = {}
    mutations.append((bad, schemas.GET_META_DOMAIN_SCHEMA))

    for output, schema in mutations:
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(output, schema)


@pytest.mark.parametrize("tool_name", _SCHEMAS)
async def test_meta_records_are_recursively_typed_and_closed(
    tool_name: str, facade: Any, call_tool: Any
) -> None:
    """Metadata rejects one isolated unknown/missing/wrong-typed nested field."""
    output = await _success(facade, call_tool, tool_name)
    command = output["_meta"]["next_commands"][0]
    mutations = []

    bad = deepcopy(output)
    bad["_meta"]["data_versions"]["unknown_release"] = "x"
    mutations.append(bad)
    bad = deepcopy(output)
    bad["_meta"]["data_versions"].pop("pfam")
    mutations.append(bad)
    bad = deepcopy(output)
    bad["_meta"]["next_commands"][0]["unknown"] = True
    mutations.append(bad)
    bad = deepcopy(output)
    bad["_meta"]["next_commands"][0].pop("arguments")
    mutations.append(bad)
    bad = deepcopy(output)
    bad["_meta"]["next_commands"][0]["arguments"] = []
    mutations.append(bad)
    bad = deepcopy(output)
    bad["_meta"]["next_commands"][0]["reason"] = 7
    mutations.append(bad)

    assert command["tool"] and isinstance(command["arguments"], dict)
    for mutation in mutations:
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(mutation, _SCHEMAS[tool_name])


@pytest.mark.parametrize("tool_name", _SCHEMAS)
async def test_allowed_values_are_string_items(tool_name: str, facade: Any, call_tool: Any) -> None:
    """The middleware emits string constraints/names; arbitrary values are invalid."""
    output = await _success(facade, call_tool, tool_name)
    error = {
        "success": False,
        "_meta": output["_meta"],
        **_ERROR_FIELDS,
        "allowed_values": [{}],
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(error, _SCHEMAS[tool_name])


async def test_all_preserved_optional_v2_fields_validate_but_extras_do_not(
    facade: Any, call_tool: Any
) -> None:
    """Strict upstream optional fields remain representable on every output path."""
    from metadome_link.api import models

    # Fail closed if a future strict upstream model accepts another optional key
    # without this wire-contract test being extended alongside it.
    assert set(models._POSITION_OPTIONAL_FIELDS) == {"exon_numbers", "ClinVar"}
    assert set(models._CLINVAR_OPTIONAL_FIELDS) == {"clinvar_clinsig"}
    assert set(models._METADOMAIN_OPTIONAL_FIELDS) == {
        "exon_numbers",
        "clinvar_clinsig",
    }
    landscape = await _success(facade, call_tool, "get_tolerance_landscape")
    variant_counts = await _success(facade, call_tool, "get_variant_counts")
    meta_domain = await _success(facade, call_tool, "get_meta_domain")

    landscape["positional_annotation"][0]["exon_numbers"] = "5, 5, 5"
    clinvar = variant_counts["positions"][0]["clinvar_variants"][0]
    clinvar["clinvar_clinsig"] = "Pathogenic"
    block = next(iter(meta_domain["meta_domains"].values()))
    block["normal_variants"][0]["exon_numbers"] = "5, 5, 5"
    block["pathogenic_variants"][0]["exon_numbers"] = "5, 5, 5"
    block["pathogenic_variants"][0]["clinvar_clinsig"] = "Pathogenic"

    jsonschema.validate(landscape, schemas.GET_TOLERANCE_LANDSCAPE_SCHEMA)
    jsonschema.validate(variant_counts, schemas.GET_VARIANT_COUNTS_SCHEMA)
    jsonschema.validate(meta_domain, schemas.GET_META_DOMAIN_SCHEMA)

    for output, schema, target in (
        (
            landscape,
            schemas.GET_TOLERANCE_LANDSCAPE_SCHEMA,
            landscape["positional_annotation"][0],
        ),
        (variant_counts, schemas.GET_VARIANT_COUNTS_SCHEMA, clinvar),
        (meta_domain, schemas.GET_META_DOMAIN_SCHEMA, block["normal_variants"][0]),
    ):
        bad = deepcopy(output)
        # Locate the copied target by using the same stable shape-specific path.
        if schema is schemas.GET_TOLERANCE_LANDSCAPE_SCHEMA:
            copied_target = bad["positional_annotation"][0]
        elif schema is schemas.GET_VARIANT_COUNTS_SCHEMA:
            copied_target = bad["positions"][0]["clinvar_variants"][0]
        else:
            copied_target = next(iter(bad["meta_domains"].values()))["normal_variants"][0]
        assert target
        copied_target["unknown_live_field"] = "x"
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(bad, schema)


async def test_tool_description_signatures_are_generated_from_advertised_inputs(
    facade: Any,
) -> None:
    """Every first sentence ends with the exact current list_tools signature."""
    async with Client(facade) as client:
        tools = await client.list_tools()
    assert len(tools) == 11
    for tool in tools:
        properties = tool.inputSchema.get("properties", {})
        required = set(tool.inputSchema.get("required", []))
        arguments = ", ".join(name if name in required else f"{name}=" for name in properties)
        signature = f"Signature: {tool.name}({arguments})."
        first_sentence = (tool.description or "").split("\n", maxsplit=1)[0]
        assert first_sentence.endswith(signature), (tool.name, first_sentence, signature)
        assert ". Signature:" not in first_sentence, (tool.name, first_sentence)
