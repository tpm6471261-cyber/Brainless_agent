"""Deterministic benchmark harness for runtime-owned local scenarios."""
from __future__ import annotations
from dataclasses import dataclass
from time import monotonic
from typing import Awaitable, Callable
@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    name:str; success:bool; verified:bool; steps:int; retries:int; duration_ms:float; agents:int; reasoning_calls:int; recoveries:int; user_interventions:int
class BenchmarkHarness:
    async def run(self,name:str, scenario:Callable[[], Awaitable[tuple[bool,bool,dict[str,int]]]])->BenchmarkResult:
        started=monotonic(); success,verified,metrics=await scenario()
        return BenchmarkResult(name,success,verified,metrics.get("steps",0),metrics.get("retries",0),(monotonic()-started)*1000,
                               metrics.get("agents",0),metrics.get("reasoning_calls",0),metrics.get("recoveries",0),metrics.get("user_interventions",0))
