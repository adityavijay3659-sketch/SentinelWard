from __future__ import annotations

from datetime import datetime
from typing import Protocol

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore  # type: ignore[import-untyped]
from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]


class EscalationTarget(Protocol):
    async def escalate_due(self, alert_id: str, expected_step: int) -> object: ...


_TARGET: EscalationTarget | None = None


def register_escalation_target(target: EscalationTarget) -> None:
    global _TARGET
    _TARGET = target


async def run_escalation_job(alert_id: str, expected_step: int) -> None:
    if _TARGET is None:
        raise RuntimeError("A1 escalation target is not registered")
    await _TARGET.escalate_due(alert_id, expected_step)


class DurableAlertScheduler:
    def __init__(self, database_url: str) -> None:
        sqlalchemy_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
        self._scheduler = AsyncIOScheduler(
            jobstores={
                "default": SQLAlchemyJobStore(
                    url=sqlalchemy_url,
                    tablename="apscheduler_jobs",
                    tableschema="automation",
                )
            },
            timezone="UTC",
        )

    def start(self) -> None:
        self._scheduler.start()

    async def schedule(self, alert_id: str, step: int, run_at: datetime) -> None:
        self._scheduler.add_job(
            run_escalation_job,
            trigger="date",
            run_date=run_at,
            args=[alert_id, step],
            id=job_id(alert_id, step),
            replace_existing=True,
            misfire_grace_time=30,
        )

    async def cancel(self, alert_id: str) -> None:
        for step in (2, 3):
            identifier = job_id(alert_id, step)
            if self._scheduler.get_job(identifier) is not None:
                self._scheduler.remove_job(identifier)

    async def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=True)


def job_id(alert_id: str, step: int) -> str:
    return f"a1:{alert_id}:step:{step}"
