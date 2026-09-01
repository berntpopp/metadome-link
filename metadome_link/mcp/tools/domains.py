"""Domain tools: ``get_protein_domains`` and ``get_meta_domain`` (Task 12).

Both are thin MCP wrappers over :class:`MetaDomeService`, mirroring
``discovery.py``: each tool body wraps a service call in a ``call()`` closure,
sets ``_meta.next_commands`` via a local ``after_*`` builder, and returns
``run_mcp_tool(name, call, context=McpErrorContext(...))`` so the envelope adds
``success`` / ``_meta`` and converts typed exceptions into structured errors.

- ``get_protein_domains`` projects the cached landscape's top-level Pfam
  ``domains[]`` (ID / Name / start / stop / metadomain / alignment depth).
- ``get_meta_domain`` returns homologous (meta-domain) variant detail for one
  residue. The optional ``domains`` mapping (``{PfamID: [consensus_pos, ...]}``)
  selects which meta-domains to fetch; when omitted the service derives it from
  the cached residue's ``domains`` map. A residue with no meta-domain mapping
  yields empty ``meta_domains`` -- a success, NOT an error.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field, StrictInt

from metadome_link.constants import (
    MAX_GENOMIC_POSITION,
    MAX_META_DOMAIN_SELECTOR_DOMAINS,
    MAX_META_DOMAIN_SELECTOR_KEY_CHARS,
    MAX_META_DOMAIN_SELECTOR_POSITIONS_PER_DOMAIN,
)
from metadome_link.mcp import schemas as output_schemas
from metadome_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from metadome_link.mcp.envelope import McpErrorContext, ToolReturn, run_mcp_tool
from metadome_link.mcp.next_commands import cmd
from metadome_link.mcp.service_adapters import get_metadome_service
from metadome_link.mcp.tools._common import (
    LimitArg,
    OffsetArg,
    PositionArg,
    ResponseMode,
    TranscriptIdArg,
)

if TYPE_CHECKING:
    from fastmcp import FastMCP

#: Default page size for the homologous variant lists in ``get_meta_domain``.
_DEFAULT_META_DOMAIN_LIMIT = 100

#: Optional ``{PfamID: [consensus_pos, ...]}`` meta-domain selector. Omit to let
#: the service derive it from the cached residue's ``domains`` map.
_DomainSelectorMap = Annotated[
    dict[
        str,
        Annotated[
            list[Annotated[StrictInt, Field(ge=1, le=MAX_GENOMIC_POSITION)]],
            Field(min_length=1, max_length=MAX_META_DOMAIN_SELECTOR_POSITIONS_PER_DOMAIN),
        ],
    ],
    Field(
        max_length=MAX_META_DOMAIN_SELECTOR_DOMAINS,
        json_schema_extra={
            "propertyNames": {
                "type": "string",
                "minLength": 1,
                "maxLength": MAX_META_DOMAIN_SELECTOR_KEY_CHARS,
            }
        },
    ),
]
DomainsArg = Annotated[
    _DomainSelectorMap | None,
    Field(
        default=None,
        description="Optional Pfam-to-consensus-position selector; omitted derives from residue.",
    ),
]


def _after_get_protein_domains(transcript_id: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Next steps after listing Pfam domains: drill into a domain's meta-domain.

    Picks the first metadomain-bearing Pfam domain (if any) and offers a
    ``get_meta_domain`` call at its start residue, plus the broader landscape /
    intolerant-region summaries.
    """
    domains = payload.get("domains")
    domain_list = domains if isinstance(domains, list) else []
    steps: list[dict[str, Any]] = []
    for domain in domain_list:
        if isinstance(domain, dict) and domain.get("metadomain") and domain.get("start"):
            steps.append(
                cmd(
                    "get_meta_domain",
                    transcript_id=transcript_id,
                    position=int(domain["start"]),
                )
            )
            break
    steps.append(cmd("summarize_intolerant_regions", transcript_id=transcript_id))
    steps.append(cmd("get_tolerance_landscape", transcript_id=transcript_id))
    return steps


def _after_get_meta_domain(
    transcript_id: str, position: int, payload: dict[str, Any]
) -> list[dict[str, Any]]:
    """Next steps after a meta-domain lookup: page variants or step back out.

    When any variant list is truncated, offer the next page (advancing ``offset``);
    always offer the residue's tolerance context and the full domain list.
    """
    steps: list[dict[str, Any]] = []
    meta_domains = payload.get("meta_domains")
    requested_domains = payload.get("requested_domains")
    if isinstance(meta_domains, dict):
        for block in meta_domains.values():
            if not isinstance(block, dict):
                continue
            pagination = block.get("pagination")
            if not isinstance(pagination, dict):
                continue
            for page_block in pagination.values():
                if isinstance(page_block, dict) and page_block.get("truncated"):
                    next_offset = page_block.get("next_offset")
                    if next_offset is not None:
                        steps.append(
                            cmd(
                                "get_meta_domain",
                                transcript_id=transcript_id,
                                position=position,
                                **(
                                    {"domains": requested_domains}
                                    if isinstance(requested_domains, dict)
                                    else {}
                                ),
                                limit=int(page_block.get("limit", _DEFAULT_META_DOMAIN_LIMIT)),
                                offset=int(next_offset),
                            )
                        )
                        break
            if steps:
                break
    steps.append(cmd("get_position_tolerance", transcript_id=transcript_id, position=position))
    steps.append(cmd("get_protein_domains", transcript_id=transcript_id))
    return steps


def register_domain_tools(mcp: FastMCP) -> None:
    """Register the domain tools (``get_protein_domains``, ``get_meta_domain``)."""

    @mcp.tool(
        name="get_protein_domains",
        title="Get Protein Domains",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=output_schemas.GET_PROTEIN_DOMAINS_SCHEMA,
        tags={"domains"},
        description=(
            "List protein domains; Signature: get_protein_domains(transcript_id, response_mode=)."
        ),
    )
    async def get_protein_domains(
        transcript_id: TranscriptIdArg,
        response_mode: ResponseMode = "compact",
    ) -> ToolReturn:
        async def call() -> dict[str, Any]:
            service = get_metadome_service()
            payload = await service.get_domains(transcript_id, response_mode=response_mode)
            payload.setdefault("_meta", {})["next_commands"] = _after_get_protein_domains(
                transcript_id, payload
            )
            return payload

        return await run_mcp_tool(
            "get_protein_domains",
            call,
            context=McpErrorContext(
                "get_protein_domains",
                arguments={"transcript_id": transcript_id},
                response_mode=response_mode,
            ),
        )

    @mcp.tool(
        name="get_meta_domain",
        title="Get Meta-Domain Variants",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=output_schemas.GET_META_DOMAIN_SCHEMA,
        tags={"domains"},
        description=(
            "Return paginated meta-domain variants; "
            "Signature: get_meta_domain(transcript_id, position, domains=, limit=, offset=, "
            "response_mode=)."
        ),
    )
    async def get_meta_domain(
        transcript_id: TranscriptIdArg,
        position: PositionArg,
        domains: DomainsArg = None,
        limit: LimitArg = _DEFAULT_META_DOMAIN_LIMIT,
        offset: OffsetArg = 0,
        response_mode: ResponseMode = "compact",
    ) -> ToolReturn:
        async def call() -> dict[str, Any]:
            service = get_metadome_service()
            payload = await service.get_meta_domain(
                transcript_id,
                position,
                domains=domains,
                limit=limit,
                offset=offset,
                response_mode=response_mode,
            )
            payload.setdefault("_meta", {})["next_commands"] = _after_get_meta_domain(
                transcript_id, position, payload
            )
            return payload

        return await run_mcp_tool(
            "get_meta_domain",
            call,
            context=McpErrorContext(
                "get_meta_domain",
                arguments={
                    "transcript_id": transcript_id,
                    "position": position,
                    "domains": domains,
                    "limit": limit,
                    "offset": offset,
                },
                response_mode=response_mode,
            ),
        )
