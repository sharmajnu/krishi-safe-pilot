"""Per-request GPU energy measurement.

Three backends, auto-selected unless forced:
  * nvml  — NVML total-energy counter delta (Volta+): most accurate.
  * poll  — 10 Hz power polling integrated over the request window.
  * dummy — no GPU: synthetic joules from wall time, for pipeline testing.

GPU-only measurement (excludes CPU/DRAM/cooling) — pilot-grade; say so in
any output. Self-test: python -m src.energy
"""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator


@dataclass
class Measurement:
    joules: float = 0.0
    seconds: float = 0.0
    method: str = ""
    samples: int = 0  # poll mode only


@dataclass
class DeviceInfo:
    name: str = "none (dummy mode)"
    driver: str = ""
    power_limit_w: float = 0.0
    extra: dict = field(default_factory=dict)


class BaseMeter:
    method = "base"

    @contextmanager
    def measure(self) -> Iterator[Measurement]:
        raise NotImplementedError

    def device_info(self) -> DeviceInfo:
        return DeviceInfo()

    def idle_baseline(self, seconds: float = 10.0) -> float:
        """Mean idle power in watts, measured over `seconds`."""
        with self.measure() as m:
            time.sleep(seconds)
        return m.joules / max(m.seconds, 1e-9)


class DummyMeter(BaseMeter):
    """Synthetic energy: wall time x a fixed fake power draw."""

    method = "dummy"
    FAKE_POWER_W = 60.0

    @contextmanager
    def measure(self) -> Iterator[Measurement]:
        m = Measurement(method=self.method)
        t0 = time.monotonic()
        try:
            yield m
        finally:
            m.seconds = max(time.monotonic() - t0, 1e-3)
            m.joules = m.seconds * self.FAKE_POWER_W

    def idle_baseline(self, seconds: float = 10.0) -> float:
        return self.FAKE_POWER_W  # no need to actually wait in dummy mode


class _NvmlMixin:
    def __init__(self, device_index: int = 0):
        # lazy: only needed for real measurement. Install the 'nvidia-ml-py'
        # package (NOT the deprecated 'pynvml' package) to provide this module.
        import pynvml

        self._nvml = pynvml
        pynvml.nvmlInit()
        self._handle = pynvml.nvmlDeviceGetHandleByIndex(device_index)

    def device_info(self) -> DeviceInfo:
        nv, h = self._nvml, self._handle
        name = nv.nvmlDeviceGetName(h)
        if isinstance(name, bytes):
            name = name.decode()
        driver = nv.nvmlSystemGetDriverVersion()
        if isinstance(driver, bytes):
            driver = driver.decode()
        limit = nv.nvmlDeviceGetPowerManagementLimit(h) / 1000.0
        return DeviceInfo(name=name, driver=driver, power_limit_w=limit)


class NvmlCounterMeter(_NvmlMixin, BaseMeter):
    """Total-energy counter delta (mJ). Requires Volta or newer."""

    method = "nvml"

    def __init__(self, device_index: int = 0):
        super().__init__(device_index)
        self._read()  # raises NVMLError if unsupported -> caller falls back

    def _read(self) -> float:
        return self._nvml.nvmlDeviceGetTotalEnergyConsumption(self._handle) / 1000.0

    @contextmanager
    def measure(self) -> Iterator[Measurement]:
        m = Measurement(method=self.method)
        e0, t0 = self._read(), time.monotonic()
        try:
            yield m
        finally:
            m.seconds = time.monotonic() - t0
            m.joules = self._read() - e0


class NvmlPollingMeter(_NvmlMixin, BaseMeter):
    """Integrate nvmlDeviceGetPowerUsage samples at `hz` over the window."""

    method = "poll"

    def __init__(self, device_index: int = 0, hz: float = 10.0):
        super().__init__(device_index)
        self._interval = 1.0 / hz

    @contextmanager
    def measure(self) -> Iterator[Measurement]:
        m = Measurement(method=self.method)
        samples: list[tuple[float, float]] = []  # (t, watts)
        stop = threading.Event()

        def poll() -> None:
            while not stop.is_set():
                w = self._nvml.nvmlDeviceGetPowerUsage(self._handle) / 1000.0
                samples.append((time.monotonic(), w))
                stop.wait(self._interval)

        t0 = time.monotonic()
        thread = threading.Thread(target=poll, daemon=True)
        thread.start()
        try:
            yield m
        finally:
            stop.set()
            thread.join(timeout=2.0)
            m.seconds = time.monotonic() - t0
            m.samples = len(samples)
            # trapezoidal integration; pad endpoints with the window bounds
            if samples:
                pts = [(t0, samples[0][1])] + samples + [(t0 + m.seconds, samples[-1][1])]
                m.joules = sum(
                    (pts[i + 1][0] - pts[i][0]) * (pts[i][1] + pts[i + 1][1]) / 2.0
                    for i in range(len(pts) - 1)
                )


def get_meter(mode: str = "auto", device_index: int = 0, poll_hz: float = 10.0) -> BaseMeter:
    if mode == "dummy":
        return DummyMeter()
    if mode == "nvml":
        return NvmlCounterMeter(device_index)
    if mode == "poll":
        return NvmlPollingMeter(device_index, poll_hz)
    if mode == "auto":
        try:
            return NvmlCounterMeter(device_index)
        except Exception:
            pass
        try:
            return NvmlPollingMeter(device_index, poll_hz)
        except Exception:
            print("energy: no NVML available, falling back to DUMMY meter "
                  "(synthetic joules — pipeline testing only)")
            return DummyMeter()
    raise ValueError(f"unknown energy mode '{mode}'")


if __name__ == "__main__":
    meter = get_meter("auto")
    info = meter.device_info()
    print(f"meter={meter.method}  device={info.name}  driver={info.driver}  "
          f"power_limit={info.power_limit_w}W")
    with meter.measure() as m:
        time.sleep(0.5)
    print(f"self-test: {m.joules:.2f} J over {m.seconds:.3f} s "
          f"({m.joules / m.seconds:.1f} W mean, method={m.method})")
    print(f"idle baseline (2 s sample): {meter.idle_baseline(2.0):.1f} W")
