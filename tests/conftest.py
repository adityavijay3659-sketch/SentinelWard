from __future__ import annotations

import asyncio
import json
import selectors
import sys
from pathlib import Path
from typing import Any

import pytest


def pytest_asyncio_loop_factories(config: pytest.Config, item: pytest.Item) -> dict[str, object]:
    del config, item
    if sys.platform == "win32":
        return {"selector": lambda: asyncio.SelectorEventLoop(selectors.SelectSelector())}
    return {"default": asyncio.new_event_loop}


@pytest.fixture(scope="session")
def contract_fixture() -> dict[str, Any]:
    path = Path(__file__).parents[1] / "fixtures" / "contract-examples.json"
    return json.loads(path.read_text(encoding="utf-8"))
