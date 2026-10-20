"""Release workflow pins must track the trusted fleet revisions."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# genefoundry-router v0.8.5: added `validate-deployed-overlay` and the
# ReleaseConfig fields it reads (router #172). Both container-ci.yml and
# container-release.yml load ReleaseConfig from their pinned commit, so both
# must track this revision or the older pin rejects the new fields.
ROUTER_SHA = "bab3fb6bc9a9b2a9c87bd3d5aa9883a42bae039b"
SETUP_UV_SHA = "1c37ad07a6a961277cf70c0d37d6f313000f5884"
CODEQL_SHA = "6f2ac81f5cd81fe351a197ba0b00d91d03cd2aee"


def test_release_workflows_pin_the_trusted_router_and_actions() -> None:
    workflows = ROOT / ".github" / "workflows"
    release_text = (workflows / "container-release.yml").read_text(encoding="utf-8")
    ci_text = (workflows / "container-ci.yml").read_text(encoding="utf-8")
    assert ROUTER_SHA in release_text
    assert ROUTER_SHA in ci_text
    assert SETUP_UV_SHA in (workflows / "ci.yml").read_text(encoding="utf-8")
    security_text = (workflows / "security.yml").read_text(encoding="utf-8")
    assert security_text.count(CODEQL_SHA) == 2
