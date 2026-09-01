# tests/test_identifiers.py
import pytest

from metadome_link.exceptions import InvalidInputError
from metadome_link.identifiers import (
    is_transcript_id,
    looks_like_transcript_query,
    normalize_gene_symbol,
    validate_transcript_id,
)


def test_is_transcript_id_requires_version():
    assert is_transcript_id("ENST00000269305.9")
    assert not is_transcript_id("ENST00000269305")  # no version
    assert not is_transcript_id("TP53")


def test_validate_transcript_id_raises_on_unversioned():
    with pytest.raises(InvalidInputError) as ei:
        validate_transcript_id("ENST00000269305")
    assert ei.value.error_code == "invalid_input"
    assert ei.value.extra.get("field") == "transcript_id"


def test_normalize_gene_symbol():
    assert normalize_gene_symbol(" tp53 ") == "TP53"


def test_looks_like_transcript_query():
    assert looks_like_transcript_query("ENST00000269305.9")
    assert not looks_like_transcript_query("TP53")
