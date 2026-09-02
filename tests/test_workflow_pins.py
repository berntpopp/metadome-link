"""Release workflow pins must track the trusted fleet revisions."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# genefoundry-router v0.8.5: added `validate-deployed-overlay` and the
# ReleaseConfig fields it reads (router #172). Both container-ci.yml and
# container-release.yml load ReleaseConfig from their pinned commit, so both
# must track this revision or the older pin rejects the new fields.
ROUTER_SHA = "31ea81cee5475fc3655c047c63a89739948f99a9"
SETUP_UV_SHA = "20cfd1bf945f4377ade1205e4dbc17946fc9a30d"
CODEQL_SHA = "ff2f1c621b7f889edc0d3c761ac2e6a3f8cdb0dd"


def test_release_workflows_pin_the_trusted_router_and_actions() -> None:
    workflows = ROOT / ".github" / "workflows"
    release_text = (workflows / "container-release.yml").read_text(encoding="utf-8")
    ci_text = (workflows / "container-ci.yml").read_text(encoding="utf-8")
    assert ROUTER_SHA in release_text
    assert ROUTER_SHA in ci_text
    assert SETUP_UV_SHA in (workflows / "ci.yml").read_text(encoding="utf-8")
    security_text = (workflows / "security.yml").read_text(encoding="utf-8")
    assert security_text.count(CODEQL_SHA) == 2
