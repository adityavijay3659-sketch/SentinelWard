from __future__ import annotations

import pytest

from sentinelward.m6_training import RegressionArtifact, assess, fit


def observations(patient: str) -> list[dict]:
    return [
        {
            "patient_id": patient,
            "features": [float(i), float(i % 3), float(i % 7)],
            "target_map": 70.0 + 2 * i,
            "waveform_map": 70.0 + 2 * i,
        }
        for i in range(20)
    ]


def test_ridge_fits_actual_targets_and_serializes_reproducibly() -> None:
    rows = observations("train")
    model = fit(rows, ["train"], 0.1)
    fact = assess(observations("test"), model)
    assert fact["mae_mmhg"] < 0.1
    assert fact["mae_mmhg"] < fact["training_mean_baseline_mae_mmhg"]
    restored = RegressionArtifact.model_validate_json(model.model_dump_json())
    assert restored.predict([1, 2, 3]) == model.predict([1, 2, 3])
    assert model.research_only and "not_runtime" in model.kind


def test_training_rejects_subject_leakage_missing_patients_and_invalid_ridge() -> None:
    for patients, ridge in (
        (["test"], 1),
        (["train", "missing"], 1),
        (["train", "train"], 1),
        (["train"], 0),
    ):
        with pytest.raises(ValueError):
            fit(observations("train"), patients, ridge)
    with pytest.raises(ValueError):
        fit([], ["train"], 1)


def test_preprocessing_is_fit_only_on_training_and_never_changes_during_testing() -> None:
    model = fit(observations("train"), ["train"], 1)
    before = model.model_dump_json()
    test = observations("test")
    for row in test:
        row["features"][0] += 1000
    assess(test, model)
    assert model.model_dump_json() == before
    assert model.centres[0] == 9.5


def test_constant_features_are_regularized_without_nan_or_singular_matrix() -> None:
    rows = [
        {"patient_id": "train", "features": [80, 160, 40], "target_map": 85, "waveform_map": 85}
        for _ in range(5)
    ]
    model = fit(rows, ["train"], 1)
    assert model.predict([80, 160, 40]) == 85
    assert assess(rows, model)["mae_mmhg"] == 0
