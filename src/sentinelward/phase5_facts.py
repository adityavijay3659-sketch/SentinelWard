"""Pure interval arithmetic and immutable fact-linked narrative composition."""

from __future__ import annotations

from collections.abc import Iterable

from sentinelward.phase5_contracts import Composition, Fact, FactSnapshot, Narrative, Sentence
from sentinelward.phase5_diagnostics import GenerationFailure


def union_ms(intervals: Iterable[tuple[int, int]], since: int, as_of: int) -> int:
    clipped = sorted(
        (max(a, since), min(b, as_of)) for a, b in intervals if a < as_of and b > since
    )
    total, right = 0, since
    for a, b in clipped:
        total += max(0, b - max(a, right))
        right = max(right, b)
    return total


def covered_ms(
    intervals: Iterable[tuple[int, int]],
    conflicts: Iterable[tuple[int, int]],
    since: int,
    as_of: int,
) -> int:
    known = list(intervals)
    bad = list(conflicts)
    overlap = [(max(a, x), min(b, y)) for a, b in known for x, y in bad if max(a, x) < min(b, y)]
    return union_ms(known, since, as_of) - union_ms(overlap, since, as_of)


def fact_sentence(fact: Fact, wording: str) -> str:
    # Subjects and textual values originate in a source-controlled vocabulary.
    subject = fact.subject.replace("_", " ")
    qualifier = "Measured " if fact.status == "partial" else ""
    if fact.status == "unavailable" or fact.value is None:
        return f"{subject.capitalize()} is unavailable for this interval."
    if fact.predicate == "count":
        return (
            f"{qualifier}{subject.capitalize()}: {fact.value} recorded events."
            if wording == "concise"
            else f"{qualifier}{subject.capitalize()} has {fact.value} "
            "recorded events in this interval."
        )
    if fact.predicate == "duration":
        return (
            f"{subject}: {int(fact.value) / 60_000:.2f} measured minutes; "
            f"coverage is {fact.status}."
        )
    return f"{subject.capitalize()}: {fact.value}."


def render_composition(snapshot: FactSnapshot, composition: Composition) -> str:
    indexed = {f.fact_id: f for f in snapshot.facts}
    ids = [sentence.fact_id for sentence in composition.sentences]
    # Require all facts exactly once: the model cannot omit an inconvenient fact.
    if len(ids) != len(set(ids)):
        raise GenerationFailure("duplicate_fact_id", "fact_binding")
    if set(ids) - set(indexed):
        raise GenerationFailure("unknown_fact_id", "fact_binding")
    if set(indexed) - set(ids):
        raise GenerationFailure("missing_fact_id", "fact_binding")
    output: list[str] = []
    for sentence in composition.sentences:
        fact = indexed[sentence.fact_id]
        expected = "missing" if fact.status == "unavailable" else fact.predicate
        if sentence.phrase_id != expected:
            raise GenerationFailure("predicate_mismatch", "fact_binding")
        output.append(fact_sentence(fact, sentence.wording))
    return " ".join(output)


def template(snapshot: FactSnapshot, reason: str = "generation_pending") -> Narrative:
    composition = Composition(
        sentences=[
            Sentence(
                phrase_id="missing" if f.status == "unavailable" else f.predicate,
                fact_id=f.fact_id,
            )
            for f in snapshot.facts
        ]
    )
    return Narrative(
        text=render_composition(snapshot, composition),
        generator="template",
        snapshot_hash=snapshot.source_hash,
        fallback_reason=reason,
        composition=composition,
    )
