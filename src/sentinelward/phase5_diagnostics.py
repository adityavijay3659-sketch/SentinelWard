"""Safe generation failure codes; provider text never enters normal audit."""

from __future__ import annotations


class GenerationFailure(ValueError):
    def __init__(self, code: str, stage: str) -> None:
        super().__init__(code)
        self.code = code
        self.stage = stage
