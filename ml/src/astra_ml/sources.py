from __future__ import annotations

from typing import Protocol

from .models import Measurement
from .synthetic import generate_heart_rate


class DataSource(Protocol):
    def read_batch(self) -> list[Measurement]: ...


class SimulatorSource:
    def __init__(self, scenario: str = "stable", **kwargs):
        self.scenario = scenario
        self.kwargs = kwargs

    def read_batch(self) -> list[Measurement]:
        return generate_heart_rate(self.scenario, **self.kwargs)