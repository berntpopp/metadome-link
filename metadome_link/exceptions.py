"""Custom exceptions for metadome-link.

Each subclass carries a stable ``error_code`` from the fleet's 7-code taxonomy.
The data plane (``api/``, ``cache/``, ``services/``) raises these; the MCP plane
(``mcp/envelope.py::run_mcp_tool``) catches each and converts it into a
**returned** structured error (it reads ``error_code``, ``retryable``,
``recovery_action`` and the ``extra`` dict). Errors are never raised to the
client.
"""

from __future__ import annotations


class MetaDomeError(Exception):
    """Base exception for all metadome-link data/client/service errors."""

    error_code = "internal"

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        recovery_action: str | None = None,
        **extra: object,
    ) -> None:
        """Store a human-readable message plus structured envelope hints.

        Args:
            message: Human-readable error message.
            retryable: Whether the caller may retry the same call.
            recovery_action: Optional machine hint (e.g. ``"switch_tool"``).
            **extra: Arbitrary structured fields surfaced on the error envelope
                (stored on ``self.extra``); e.g. ``field``, ``hint``, ``candidates``.
        """
        super().__init__(message)
        self.message = message
        self.retryable = retryable
        self.recovery_action = recovery_action
        self.extra: dict[str, object] = dict(extra)


class InvalidInputError(MetaDomeError):
    """A tool/service argument failed validation before any lookup ran."""

    error_code = "invalid_input"


class NotFoundError(MetaDomeError):
    """A lookup returned nothing for an otherwise valid identifier."""

    error_code = "not_found"


class AmbiguousQueryError(MetaDomeError):
    """A query matched several records and cannot be resolved unambiguously."""

    error_code = "ambiguous_query"

    def __init__(
        self,
        message: str,
        *,
        candidates: list[object],
        retryable: bool = False,
        recovery_action: str | None = None,
        **extra: object,
    ) -> None:
        """Store the ambiguous candidates so the envelope can surface them."""
        super().__init__(
            message,
            retryable=retryable,
            recovery_action=recovery_action,
            candidates=candidates,
            **extra,
        )
        self.candidates = candidates


class DataUnavailableError(MetaDomeError):
    """Required upstream landscape data is missing or could not be delivered.

    Wire error_code is ``upstream_unavailable`` (the closed six-value enum); this
    subclass is the NON-retryable variant (a completed-but-failed MetaDome build),
    distinct from the retryable :class:`UpstreamUnavailableError`.
    """

    error_code = "upstream_unavailable"


class RateLimitedError(MetaDomeError):
    """An upstream endpoint signalled rate limiting (HTTP 429)."""

    error_code = "rate_limited"


class UpstreamUnavailableError(MetaDomeError):
    """MetaDome is temporarily unavailable (5xx / timeout / job FAILURE)."""

    error_code = "upstream_unavailable"


class InternalError(MetaDomeError):
    """An unexpected internal error (the catch-all default code)."""

    error_code = "internal"


# ---------------------------------------------------------------------------
# Failure classification
# ---------------------------------------------------------------------------

#: Stacktrace fragments identifying a MetaDome build crash caused by a transcript
#: with ``has_protein_data == false`` (no UniProt mapping): the builder
#: dereferences ``_protein.id`` on a ``None`` protein.
_NO_PROTEIN_DATA_SIGNATURES = (
    "object has no attribute 'id'",
    "_protein.id",
    "self.protein_id = _protein",
)


def metadome_build_failure(transcript_id: str, error: object) -> MetaDomeError:
    """Classify a MetaDome job ``FAILURE`` into a NON-retryable, actionable error.

    A MetaDome ``FAILURE`` is a *completed* Celery job that crashed; the failure
    is cached upstream (a ``visualization_error`` file), so a re-submit returns
    the same ``FAILURE`` without re-running -- it is **not** retryable (unlike a
    5xx/timeout, which stays a retryable :class:`UpstreamUnavailableError`).
    The dominant cause is a transcript with ``has_protein_data == false`` (no
    protein mapping), which crashes the builder; that case becomes an
    ``invalid_input`` pointing the caller at a protein-coding transcript. Any
    other crash becomes a non-retryable ``upstream_unavailable``. The raw upstream
    stacktrace is used only to classify and is never echoed to the client.
    """
    stacktrace = ""
    if isinstance(error, dict):
        stacktrace = str(error.get("stacktrace") or "")
    if any(sig in stacktrace for sig in _NO_PROTEIN_DATA_SIGNATURES):
        return InvalidInputError(
            f"MetaDome cannot analyse transcript {transcript_id}: it has no protein "
            "data in MetaDome (has_protein_data=false), so no tolerance landscape can "
            "be built. Call resolve_transcript and choose a transcript where "
            "has_protein_data=true. Some genes (e.g. BRCA2) have no protein-coding "
            "transcript in MetaDome's GRCh37/Gencode-v19 dataset and cannot be analysed.",
            field="transcript_id",
            recovery_action="reformulate_input",
            transcript_id=transcript_id,
        )
    return DataUnavailableError(
        f"MetaDome's visualization build for {transcript_id} failed and the failure is "
        "cached upstream; retrying will not help. Try a different transcript via "
        "resolve_transcript, or verify the gene is analysable in MetaDome.",
        retryable=False,
        recovery_action="switch_tool",
        transcript_id=transcript_id,
    )
