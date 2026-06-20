# tests/test_config.py
from metadome_link.config import ServerSettings


def test_settings_defaults():
    s = ServerSettings()
    assert s.port == 8000
    assert s.metadome.base_url.endswith("/metadome/api")
    assert s.transport in {"unified", "http", "stdio"}


def test_constants_data_versions():
    from metadome_link.constants import DATA_VERSIONS, RECOMMENDED_CITATION

    assert DATA_VERSIONS["assembly"] == "GRCh37"
    assert "humu.23798" in RECOMMENDED_CITATION
