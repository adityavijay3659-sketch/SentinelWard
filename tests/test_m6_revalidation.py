from __future__ import annotations

from pathlib import Path

import pytest

from sentinelward.m6_demo import synthetic_frame
from sentinelward.m6_realdata import checksum
from sentinelward.m6_revalidation import ONSET, coverage, drift_metrics, modify, snapshot_sources


def test_execution_source_is_frozen_and_changed_snapshots_are_not_overwritten(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    module = source / "scorer.py"
    module.write_text("fixed implementation", encoding="utf-8")
    hashes = {"scorer.py": checksum(module)}
    snapshot = tmp_path / "snapshot"
    snapshot_sources(hashes, source, snapshot)
    assert checksum(snapshot / "scorer.py") == hashes["scorer.py"]
    snapshot_sources(hashes, source, snapshot)
    (snapshot / "scorer.py").write_text("changed snapshot", encoding="utf-8")
    with pytest.raises(ValueError, match="integrity mismatch"):
        snapshot_sources(hashes, source, snapshot)
    module.write_text("changed source", encoding="utf-8")
    with pytest.raises(ValueError, match="source changed"):
        snapshot_sources(hashes, source, tmp_path / "new-snapshot")


def test_missing_subjects_remain_explicit_not_passes() -> None:
    facts = coverage([{"patient_id": "p1"}], ["p1", "p2"])
    assert facts["status"] == "incomplete"
    assert facts["subjects_evaluable"] == 1
    assert facts["subjects_without_usable_targets"] == ["p2"]
    assert coverage([], ["p1"])["subjects_evaluable"] == 0


def test_controlled_inputs_preserve_reference_availability_and_causality() -> None:
    before = synthetic_frame(1)
    assert modify(before, "offset_plus_15") is before
    at = synthetic_frame(900)
    shifted = modify(at, "offset_plus_15")
    assert shifted.nibp == at.nibp and shifted.ecg == at.ecg
    low = modify(at, "coupled_low_pressure_control")
    assert low.nibp is not None and low.nibp.map == 55
    assert modify(synthetic_frame(901, cuff=None), "coupled_low_pressure_control").nibp is None


def test_paired_metrics_do_not_claim_already_positive_reference_as_new_detection() -> None:
    def row(variant: str, sufficient: bool = True, positive: bool = True):
        return {
            "patient_id": "p",
            "variant": variant,
            "event_active": True,
            "score": {
                "window_start": ONSET,
                "score": 0.8,
                "label": "drift",
                "extra": {
                    "inputs_sufficient": sufficient,
                    "drift_candidate": positive,
                    "emergency_compatible": False,
                },
            },
        }

    facts = drift_metrics([row("reference"), row("offset_plus_15")], 0.6)
    assert facts["offset_plus_15"]["incremental_predictions_over_paired_reference"] == 0
    assert facts["offset_plus_15"]["drift_predictions"] == 1
    facts = drift_metrics(
        [row("reference", positive=False), row("offset_plus_15", sufficient=False)], 0.6
    )
    assert facts["offset_plus_15"]["windows"] == 1
    assert facts["offset_plus_15"]["drift_predictions"] == 0
    assert facts["offset_plus_15"]["input_coverage"] == 0
    assert facts["amplitude_attenuation"]["status"] == "not_evaluated"
