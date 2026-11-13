"""Release workflow pins must track the trusted fleet revisions."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# genefoundry-router v0.8.5: added `validate-deployed-overlay` and the
# ReleaseConfig fields it reads (router #172). Both container-ci.yml and
# container-release.yml load ReleaseConfig from their pinned commit, so both
# must track this revision or the older pin rejects the new fields.
ROUTER_SHA = "2cd86e35373cc7b1bdd8686ed9c69ca584b00ed9"
SETUP_UV_SHA = "07a047e608db84b3d8c06cd9a7c7dcc9c355c18e"
CODEQL_SHA = "9b3254085494b55a0f7c4c2b3d2d52cc712ce370"


def test_release_workflows_pin_the_trusted_router_and_actions() -> None:
    workflows = ROOT / ".github" / "workflows"
    release_text = (workflows / "container-release.yml").read_text(encoding="utf-8")
    ci_text = (workflows / "container-ci.yml").read_text(encoding="utf-8")
    assert ROUTER_SHA in release_text
    assert ROUTER_SHA in ci_text
    assert SETUP_UV_SHA in (workflows / "ci.yml").read_text(encoding="utf-8")
    security_text = (workflows / "security.yml").read_text(encoding="utf-8")
    assert security_text.count(CODEQL_SHA) == 2
