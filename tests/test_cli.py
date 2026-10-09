from __future__ import annotations

import json

from sentinelward.cli import default_smoke_fixture


def test_default_smoke_fixture_is_packaged_compatible() -> None:
    fixture = default_smoke_fixture()
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    assert payload["fixture_set"] == "phase0-v1"
    assert payload["verdicts"]
