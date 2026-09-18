"""Release workflow pins must track the trusted fleet revisions."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# genefoundry-router v0.8.5: added `validate-deployed-overlay` and the
# ReleaseConfig fields it reads (router #172). Both container-ci.yml and
# container-release.yml load ReleaseConfig from their pinned commit, so both
# must track this revision or the older pin rejects the new fields.
ROUTER_SHA = "adfc1cffed6530d6453c9dbb40be5f4c5884b8a2"
SETUP_UV_SHA = "bec219d24cd3e171d82865faccec33120bb574f4"
CODEQL_SHA = "b96794f015dfd88f77b49b1c93e0fa7110f94c63"


def test_release_workflows_pin_the_trusted_router_and_actions() -> None:
    workflows = ROOT / ".github" / "workflows"
    release_text = (workflows / "container-release.yml").read_text(encoding="utf-8")
    ci_text = (workflows / "container-ci.yml").read_text(encoding="utf-8")
    assert ROUTER_SHA in release_text
    assert ROUTER_SHA in ci_text
    assert SETUP_UV_SHA in (workflows / "ci.yml").read_text(encoding="utf-8")
    security_text = (workflows / "security.yml").read_text(encoding="utf-8")
    assert security_text.count(CODEQL_SHA) == 2
