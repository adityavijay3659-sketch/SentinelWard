from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class HealthRegistry:
    dependencies: dict[str, bool] = field(
        default_factory=lambda: {"postgres": False, "mqtt": False, "backend": False}
    )
    counters: dict[str, int] = field(default_factory=dict)

    def set(self, dependency: str, healthy: bool) -> None:
        self.dependencies[dependency] = healthy

    def increment(self, name: str, amount: int = 1) -> None:
        self.counters[name] = self.counters.get(name, 0) + amount

    @property
    def ready(self) -> bool:
        return all(self.dependencies.values())

    def snapshot(self) -> dict[str, object]:
        return {"ready": self.ready, "dependencies": dict(self.dependencies)}

    def prometheus_text(self) -> str:
        lines = [
            "# HELP sentinelward_dependency_ready Dependency readiness (1=ready).",
            "# TYPE sentinelward_dependency_ready gauge",
        ]
        lines.extend(
            f'sentinelward_dependency_ready{{dependency="{name}"}} {1 if ready else 0}'
            for name, ready in sorted(self.dependencies.items())
        )
        lines.extend(
            [
                "# HELP sentinelward_events_total Foundation event counters.",
                "# TYPE sentinelward_events_total counter",
            ]
        )
        lines.extend(
            f'sentinelward_events_total{{event="{name}"}} {value}'
            for name, value in sorted(self.counters.items())
        )
        return "\n".join(lines) + "\n"
