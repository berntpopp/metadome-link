"""Data-plane HTTP client for the MetaDome web API.

Exposes :class:`~metadome_link.api.client.MetaDomeClient` (async, six endpoints,
submit/poll/result split) plus the typed payload shapes in
:mod:`metadome_link.api.models`.
"""

from __future__ import annotations

from metadome_link.api.client import MetaDomeClient
from metadome_link.api.models import Domain, LandscapePosition, TranscriptSummary

__all__ = [
    "Domain",
    "LandscapePosition",
    "MetaDomeClient",
    "TranscriptSummary",
]
