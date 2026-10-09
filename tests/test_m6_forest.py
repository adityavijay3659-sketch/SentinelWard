from __future__ import annotations

import math

import pytest

from sentinelward.m6_forest import ForestArtifact, TreeWeights, fit_forest, regression_metrics


def tree() -> TreeWeights:
    return TreeWeights(
        left=[1, -1, -1],
        right=[2, -1, -1],
        feature=[0, -2, -2],
        threshold=[80, -2, -2],
        value=[85, 75, 95],
    )


def test_safe_json_tree_roundtrip_and_input_validation() -> None:
    artifact = ForestArtifact(trees=[tree()], train_subjects=["train"], parameters={})
    assert artifact.predict([70, 160, 40]) == 75
    assert artifact.predict([90, 160, 40]) == 95
    restored = ForestArtifact.model_validate_json(artifact.model_dump_json())
    assert restored.predict([90, 160, 40]) == 95
    for values in ([1, 2], [math.nan, 2, 3], [1e50, 2, 3]):
        with pytest.raises(ValueError):
            artifact.predict(values)
    with pytest.raises(ValueError):
        ForestArtifact.model_validate(artifact.model_dump() | {"research_only": False})


def test_executable_or_cyclic_or_corrupt_weights_are_rejected() -> None:
    for replacement in (
        {"left": [0, -1, -1]},
        {"right": [1, -1, -1]},
        {"threshold": [math.inf, -2, -2]},
        {"feature": [3, -2, -2]},
    ):
        with pytest.raises(ValueError):
            TreeWeights.model_validate(tree().model_dump() | replacement)


def test_optional_trainer_exports_equivalent_nonexecutable_predictions() -> None:
    pytest.importorskip("sklearn")
    rows = [
        {"patient_id": "train", "features": [float(i), 160, 40], "target_map": 60 + float(i)}
        for i in range(120)
    ]
    artifact = fit_forest(rows, ["train"], depth=6, leaf=3)
    assert artifact.predict([10, 160, 40]) < artifact.predict([100, 160, 40])
    fact = regression_metrics(rows, [artifact.predict(row["features"]) for row in rows])
    assert fact["mae_mmhg"] < 4
    with pytest.raises(ValueError):
        fit_forest(rows, ["test"], depth=6, leaf=3)
