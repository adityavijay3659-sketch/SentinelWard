"""Offline nonlinear physiology regression with bounded, non-executable JSON weights."""

from __future__ import annotations

import math
import struct
from collections import Counter
from importlib import import_module
from statistics import fmean
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator


class TreeWeights(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    left: list[int] = Field(min_length=1, max_length=8191)
    right: list[int]
    feature: list[int]
    threshold: list[FiniteFloat]
    value: list[FiniteFloat]

    @model_validator(mode="after")
    def valid_tree(self) -> TreeWeights:
        n = len(self.left)
        if any(
            len(values) != n for values in (self.right, self.feature, self.threshold, self.value)
        ):
            raise ValueError("tree arrays differ in length")
        reached = {0}
        for index, (left, right, feature) in enumerate(
            zip(self.left, self.right, self.feature, strict=True)
        ):
            if index not in reached:
                raise ValueError("tree contains unreachable nodes")
            if left == right == -1:
                continue
            if not (index < left < n and index < right < n and 0 <= feature < 3):
                raise ValueError("tree contains cyclic/out-of-range children or invalid feature")
            if left in reached or right in reached or left == right:
                raise ValueError("tree children have multiple parents")
            reached.update((left, right))
        return self

    def predict(self, values: list[float]) -> float:
        index = 0
        while self.left[index] != -1:
            index = (
                self.left[index]
                if values[self.feature[index]] <= self.threshold[index]
                else self.right[index]
            )
        return self.value[index]


class ForestArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["offline_physiology_forest_not_runtime_calibration"] = (
        "offline_physiology_forest_not_runtime_calibration"
    )
    trees: list[TreeWeights] = Field(min_length=1, max_length=128)
    train_subjects: list[str] = Field(min_length=1)
    parameters: dict[str, int]
    research_only: Literal[True] = True

    def predict(self, values: list[float]) -> float:
        if len(values) != 3 or any(not math.isfinite(value) for value in values):
            raise ValueError("physiology prediction requires three finite features")
        try:
            quantized = list(struct.unpack("3f", struct.pack("3f", *values)))
        except (OverflowError, struct.error) as exc:
            raise ValueError("features exceed float32 input range") from exc
        if any(not math.isfinite(value) for value in quantized):
            raise ValueError("features exceed float32 input range")
        return fmean(tree.predict(quantized) for tree in self.trees)


def fit_forest(
    rows: list[dict[str, Any]], patients: list[str], *, depth: int, leaf: int
) -> ForestArtifact:
    if (
        not rows
        or {row["patient_id"] for row in rows} != set(patients)
        or len(set(patients)) != len(patients)
    ):
        raise ValueError(
            "forest training requires exactly the declared independent training subjects"
        )
    # Optional offline dependency; the serving package never unpickles sklearn objects.
    estimator = import_module("sklearn.ensemble").RandomForestRegressor(
        n_estimators=64, max_depth=depth, min_samples_leaf=leaf, n_jobs=2, random_state=20261009
    )
    counts = Counter(row["patient_id"] for row in rows)
    weights = [len(rows) / len(patients) / counts[row["patient_id"]] for row in rows]
    estimator.fit(
        [row["features"] for row in rows],
        [row["target_map"] for row in rows],
        sample_weight=weights,
    )
    trees = []
    for fitted in estimator.estimators_:
        tree = fitted.tree_
        trees.append(
            TreeWeights(
                left=tree.children_left.tolist(),
                right=tree.children_right.tolist(),
                feature=tree.feature.tolist(),
                threshold=tree.threshold.tolist(),
                value=[float(node[0][0]) for node in tree.value],
            )
        )
    artifact = ForestArtifact(
        trees=trees,
        train_subjects=patients,
        parameters={"depth": depth, "leaf": leaf, "trees": 64, "seed": 20261009},
    )
    for row, expected in zip(
        rows[:20], estimator.predict([row["features"] for row in rows[:20]]), strict=True
    ):
        # sklearn's tree input is float32. Export inference must share that
        # quantization (handled by the artifact below) to match threshold routing.
        if abs(artifact.predict(row["features"]) - float(expected)) > 1e-6:
            raise ValueError("JSON inference differs from trained forest")
    return artifact


def regression_metrics(rows: list[dict[str, Any]], predictions: list[float]) -> dict[str, Any]:
    if not rows:
        return {"windows": 0, "mae_mmhg": None, "rmse_mmhg": None}
    errors = [
        prediction - row["target_map"] for row, prediction in zip(rows, predictions, strict=True)
    ]
    patients = sorted({row["patient_id"] for row in rows})
    return {
        "windows": len(rows),
        "subjects": len(patients),
        "mae_mmhg": fmean(abs(error) for error in errors),
        "rmse_mmhg": math.sqrt(fmean(error**2 for error in errors)),
        "bias_mmhg": fmean(errors),
        "patient_mae_mmhg": {
            patient: fmean(
                abs(error)
                for row, error in zip(rows, errors, strict=True)
                if row["patient_id"] == patient
            )
            for patient in patients
        },
    }
