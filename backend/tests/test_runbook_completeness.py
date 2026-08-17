"""RUNBOOK.md must have one entry per `ProvisioningJob` failure code — that's the Phase 10
exit criterion ("runbooks exist for every ProvisioningJob failure code"), and the only way
to actually enforce it is a test that fails when the two drift apart, not a promise to keep
them in sync by hand."""

from __future__ import annotations

import re
from pathlib import Path

from apps.provisioning.saga import PROVISIONING_ERROR_CODES

RUNBOOK_PATH = Path(__file__).resolve().parent.parent.parent / "RUNBOOK.md"
_HEADING_RE = re.compile(r"^## ([a-z][a-z0-9_.]*)$", re.MULTILINE)


def _documented_codes() -> set[str]:
    text = RUNBOOK_PATH.read_text(encoding="utf-8")
    return set(_HEADING_RE.findall(text))


class TestRunbookCompleteness:
    def test_the_runbook_file_exists(self):
        assert RUNBOOK_PATH.is_file(), f"expected {RUNBOOK_PATH} to exist"

    def test_every_provisioning_error_code_has_a_runbook_entry(self):
        documented = _documented_codes()
        missing = set(PROVISIONING_ERROR_CODES) - documented
        assert not missing, f"RUNBOOK.md is missing entries for: {sorted(missing)}"

    def test_the_runbook_has_no_stale_entries_for_codes_that_no_longer_exist(self):
        documented = _documented_codes()
        stale = documented - set(PROVISIONING_ERROR_CODES)
        assert not stale, f"RUNBOOK.md documents codes that no longer exist: {sorted(stale)}"
