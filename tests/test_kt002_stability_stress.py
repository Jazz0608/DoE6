#!/usr/bin/env python3
"""KT002 Phase 6A minimum stability and stress hardware test.

This program supports both the short Smoke Test and the formal Phase 6A run.
It tests one verified KT002 channel with a full Fixed-PDO charger and no load.

Smoke Test example:
    sudo .venv/bin/python -m tests.test_kt002_stability_stress \
      --ping-count 10 --lua-ping-count 10 --pdo-cycles 2

Formal Phase 6A example:
    sudo .venv/bin/python -m tests.test_kt002_stability_stress \
      --ping-count 100 --lua-ping-count 100 --pdo-cycles 20

The program writes:
    - CSV detail log for every operation
    - JSON summary with counts, latency, resources, and final safety state

Safety requirements:
    - Use the verified charger supporting 5V, 9V, 12V, 15V, and 20V.
    - Verified onBoot.lua must be running.
    - Electronic load must be disconnected or Input OFF.
    - KT Toolbox must not be connected.
    - KT002 PC USB must remain connected throughout the test.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import resource
import statistics
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from drivers.kt002 import (
    KT002CommandResult,
    KT002Controller,
    KT002Error,
    KT002PDOResult,
    KT002VoltageVerificationError,
)


PDO_SEQUENCE = (5, 9, 12, 15, 20, 5)
DEFAULT_OUTPUT_DIR = Path("analysis/kt002_phase6a")


@dataclass(slots=True)
class OperationRecord:
    timestamp: str
    elapsed_s: float
    stage: str
    iteration: int
    command: str
    success: bool
    latency_s: float
    reply_header: str = ""
    requested_voltage: int | None = None
    measured_voltage: float | None = None
    pdo_index: int | None = None
    voltage_error: float | None = None
    result_type: str = ""
    raw_text: str = ""
    exception_type: str = ""
    exception_message: str = ""
    rss_kib: int | None = None
    fd_count: int | None = None


class StressRun:
    """Collect operation records and summary statistics."""

    def __init__(self, csv_path: Path) -> None:
        self.csv_path = csv_path
        self.records: list[OperationRecord] = []
        self.started_monotonic = time.monotonic()
        self.started_at = utc_now()
        self._csv_file = csv_path.open("w", encoding="utf-8", newline="")
        self._writer = csv.DictWriter(
            self._csv_file,
            fieldnames=list(OperationRecord.__dataclass_fields__),
        )
        self._writer.writeheader()
        self._csv_file.flush()

    def add(self, record: OperationRecord) -> None:
        self.records.append(record)
        self._writer.writerow(asdict(record))
        self._csv_file.flush()

    def close(self) -> None:
        self._csv_file.close()

    @property
    def success_count(self) -> int:
        return sum(record.success for record in self.records)

    @property
    def failure_count(self) -> int:
        return len(self.records) - self.success_count

    def latencies(self, stage: str | None = None) -> list[float]:
        return [
            record.latency_s
            for record in self.records
            if record.success and (stage is None or record.stage == stage)
        ]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def get_rss_kib() -> int:
    """Return maximum resident set size reported by the current process."""
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)


def get_fd_count() -> int | None:
    """Return the current open file-descriptor count on Linux."""
    try:
        return len(list(Path("/proc/self/fd").iterdir()))
    except OSError:
        return None


def make_record(
    run: StressRun,
    *,
    stage: str,
    iteration: int,
    command: str,
    success: bool,
    latency_s: float,
    **kwargs: Any,
) -> OperationRecord:
    return OperationRecord(
        timestamp=utc_now(),
        elapsed_s=round(time.monotonic() - run.started_monotonic, 6),
        stage=stage,
        iteration=iteration,
        command=command,
        success=success,
        latency_s=round(latency_s, 6),
        rss_kib=get_rss_kib(),
        fd_count=get_fd_count(),
        **kwargs,
    )


def execute_operation(
    run: StressRun,
    *,
    stage: str,
    iteration: int,
    command: str,
    operation: Callable[[], Any],
) -> Any:
    """Execute, record, print, and re-raise one operation."""
    started = time.monotonic()
    try:
        result = operation()
        latency = time.monotonic() - started
        fields: dict[str, Any] = {"result_type": type(result).__name__}

        if hasattr(result, "header"):
            fields["reply_header"] = f"0x{result.header:08X}"
        if isinstance(result, KT002CommandResult):
            fields["raw_text"] = result.raw_text
        if isinstance(result, KT002PDOResult):
            fields.update(
                requested_voltage=result.requested_voltage,
                measured_voltage=result.measured_voltage,
                pdo_index=result.pdo_index,
                voltage_error=result.voltage_error,
                raw_text=result.raw_text,
            )

        run.add(
            make_record(
                run,
                stage=stage,
                iteration=iteration,
                command=command,
                success=True,
                latency_s=latency,
                **fields,
            )
        )
        return result
    except Exception as error:
        latency = time.monotonic() - started
        run.add(
            make_record(
                run,
                stage=stage,
                iteration=iteration,
                command=command,
                success=False,
                latency_s=latency,
                exception_type=type(error).__name__,
                exception_message=str(error),
                raw_text=str(getattr(error, "raw_text", "") or ""),
                requested_voltage=getattr(error, "requested_voltage", None),
                pdo_index=getattr(error, "pdo_index", None),
            )
        )
        raise


def validate_pdo(result: KT002PDOResult, voltage: int, tolerance: float) -> None:
    if not isinstance(result, KT002PDOResult):
        raise TypeError("set_voltage_result() did not return KT002PDOResult")
    if not result.success or result.requested_voltage != voltage:
        raise RuntimeError(
            f"Invalid PDO result for PD_{voltage}V: {result!r}"
        )
    if result.absolute_voltage_error > tolerance:
        raise KT002VoltageVerificationError(
            f"PD_{voltage}V measured {result.measured_voltage:.3f}V, "
            f"outside +/-{tolerance:.3f}V tolerance",
            requested_voltage=float(voltage),
            measured_voltage=result.measured_voltage,
            tolerance=tolerance,
        )


def latency_summary(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"count": 0, "min_s": None, "mean_s": None, "max_s": None}
    return {
        "count": len(values),
        "min_s": round(min(values), 6),
        "mean_s": round(statistics.fmean(values), 6),
        "max_s": round(max(values), 6),
    }


def build_summary(
    run: StressRun,
    *,
    args: argparse.Namespace,
    finished_at: str,
    final_5v_confirmed: bool,
    usb_closed: bool,
    initial_rss_kib: int,
    initial_fd_count: int | None,
) -> dict[str, Any]:
    final_rss_kib = get_rss_kib()
    final_fd_count = get_fd_count()
    exception_counts: dict[str, int] = {}
    for record in run.records:
        if record.exception_type:
            exception_counts[record.exception_type] = (
                exception_counts.get(record.exception_type, 0) + 1
            )

    total = len(run.records)
    return {
        "test": "KT002 Phase 6A minimum stability and stress",
        "started_at": run.started_at,
        "finished_at": finished_at,
        "duration_s": round(time.monotonic() - run.started_monotonic, 3),
        "configuration": {
            "protocol_ping_count": args.ping_count,
            "lua_ping_count": args.lua_ping_count,
            "pdo_cycles": args.pdo_cycles,
            "pdo_sequence": list(PDO_SEQUENCE),
            "pdo_pause_s": args.pdo_pause,
            "tolerance_v": args.tolerance,
            "continue_on_error": args.continue_on_error,
        },
        "operations": {
            "total": total,
            "success": run.success_count,
            "failure": run.failure_count,
            "success_rate_percent": (
                round(100.0 * run.success_count / total, 6) if total else 0.0
            ),
            "exception_counts": exception_counts,
        },
        "latency": {
            "all": latency_summary(run.latencies()),
            "protocol_ping": latency_summary(run.latencies("protocol_ping")),
            "lua_ping": latency_summary(run.latencies("lua_ping")),
            "pdo": latency_summary(run.latencies("pdo")),
        },
        "resources": {
            "initial_rss_kib": initial_rss_kib,
            "final_rss_kib": final_rss_kib,
            "rss_delta_kib": final_rss_kib - initial_rss_kib,
            "initial_fd_count": initial_fd_count,
            "final_fd_count": final_fd_count,
            "fd_delta": (
                final_fd_count - initial_fd_count
                if final_fd_count is not None and initial_fd_count is not None
                else None
            ),
        },
        "safety": {
            "final_5v_confirmed": final_5v_confirmed,
            "usb_closed": usb_closed,
        },
        "pass": (
            run.failure_count == 0 and final_5v_confirmed and usb_closed
        ),
        "csv_log": str(run.csv_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="KT002 Phase 6A minimum stability and stress test"
    )
    parser.add_argument("--ping-count", type=int, default=100)
    parser.add_argument("--lua-ping-count", type=int, default=100)
    parser.add_argument("--pdo-cycles", type=int, default=20)
    parser.add_argument("--pdo-pause", type=float, default=1.0)
    parser.add_argument("--tolerance", type=float, default=1.0)
    parser.add_argument("--ping-timeout", type=float, default=5.0)
    parser.add_argument("--pdo-timeout", type=float, default=8.0)
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    if args.ping_count < 0 or args.lua_ping_count < 0:
        parser.error("PING counts must not be negative")
    if args.pdo_cycles < 0:
        parser.error("--pdo-cycles must not be negative")
    if args.pdo_pause < 0:
        parser.error("--pdo-pause must not be negative")
    if args.tolerance <= 0 or args.ping_timeout <= 0 or args.pdo_timeout <= 0:
        parser.error("tolerance and timeouts must be greater than zero")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = args.output_dir / f"kt002_phase6a_{run_id}.csv"
    json_path = args.output_dir / f"kt002_phase6a_{run_id}_summary.json"

    print("=" * 72)
    print("KT002 Phase 6A minimum stability and stress test")
    print(f"Protocol PING count: {args.ping_count}")
    print(f"Lua PING count: {args.lua_ping_count}")
    print(f"PDO cycles: {args.pdo_cycles}")
    print(f"PDO sequence: {' -> '.join(map(str, PDO_SEQUENCE))}V")
    print(f"CSV log: {csv_path}")
    print(f"JSON summary: {json_path}")
    print("Electronic load must be disconnected or Input OFF.")
    print("=" * 72)

    run = StressRun(csv_path)
    controller = KT002Controller(timeout=3.0)
    initial_rss_kib = get_rss_kib()
    initial_fd_count = get_fd_count()
    final_5v_confirmed = False
    usb_closed = False
    return_code = 0

    try:
        controller.connect()
        print(f"Connected: VID={controller.VID:04X} PID={controller.pid:04X}")

        for index in range(1, args.ping_count + 1):
            reply = execute_operation(
                run,
                stage="protocol_ping",
                iteration=index,
                command="PROTOCOL_PING",
                operation=controller.ping,
            )
            if reply.header != controller.PING_REPLY_HEADER:
                raise RuntimeError(f"Unexpected PING header 0x{reply.header:08X}")
            if index == 1 or index % 10 == 0 or index == args.ping_count:
                print(f"Protocol PING: {index}/{args.ping_count} PASS")

        for index in range(1, args.lua_ping_count + 1):
            result = execute_operation(
                run,
                stage="lua_ping",
                iteration=index,
                command="PING",
                operation=lambda: controller.lua_ping_result(
                    timeout=args.ping_timeout
                ),
            )
            if not isinstance(result, KT002CommandResult):
                raise TypeError("Lua PING returned wrong result type")
            if not result.success or result.raw_text != "PONG:KT002":
                raise RuntimeError(f"Unexpected Lua PING result: {result!r}")
            if index == 1 or index % 10 == 0 or index == args.lua_ping_count:
                print(f"Lua PING: {index}/{args.lua_ping_count} PASS")

        abort_pdo = False
        for cycle in range(1, args.pdo_cycles + 1):
            print(f"PDO cycle {cycle}/{args.pdo_cycles}")
            for voltage in PDO_SEQUENCE:
                try:
                    result = execute_operation(
                        run,
                        stage="pdo",
                        iteration=cycle,
                        command=f"PD_{voltage}V",
                        operation=lambda voltage=voltage: (
                            controller.set_voltage_result(
                                voltage,
                                timeout=args.pdo_timeout,
                            )
                        ),
                    )
                    validate_pdo(result, voltage, args.tolerance)
                    print(
                        f"  PD_{voltage}V PASS: "
                        f"{result.measured_voltage:.3f}V, PDO={result.pdo_index}"
                    )
                except Exception as error:
                    print(
                        f"  PD_{voltage}V FAIL: "
                        f"{type(error).__name__}: {error}"
                    )
                    return_code = 1
                    if not args.continue_on_error:
                        abort_pdo = True
                        break
                if args.pdo_pause:
                    time.sleep(args.pdo_pause)
            if abort_pdo:
                break

        print("Final safety step: requesting PD_5V...")
        final_result = execute_operation(
            run,
            stage="final_safety",
            iteration=1,
            command="PD_5V",
            operation=lambda: controller.set_voltage_result(
                5,
                timeout=args.pdo_timeout,
            ),
        )
        validate_pdo(final_result, 5, args.tolerance)
        final_5v_confirmed = True
        print(f"Final 5V PASS: {final_result.raw_text}")

    except KeyboardInterrupt:
        print("ABORT: test interrupted by operator")
        return_code = 130
    except (KT002Error, RuntimeError, TypeError, ValueError) as error:
        print(f"FAIL: {type(error).__name__}: {error}")
        return_code = 1
    finally:
        if controller.connected and not final_5v_confirmed:
            print("Safety recovery: attempting PD_5V...")
            try:
                result = execute_operation(
                    run,
                    stage="safety_recovery",
                    iteration=1,
                    command="PD_5V",
                    operation=lambda: controller.set_voltage_result(
                        5,
                        timeout=args.pdo_timeout,
                    ),
                )
                validate_pdo(result, 5, args.tolerance)
                final_5v_confirmed = True
                print(f"Safety recovery PASS: {result.raw_text}")
            except Exception as error:
                print(f"WARNING: safety recovery failed: {error}")

        controller.close()
        usb_closed = not controller.connected
        print("KT002 USB connection closed")

        finished_at = utc_now()
        summary = build_summary(
            run,
            args=args,
            finished_at=finished_at,
            final_5v_confirmed=final_5v_confirmed,
            usb_closed=usb_closed,
            initial_rss_kib=initial_rss_kib,
            initial_fd_count=initial_fd_count,
        )
        run.close()
        json_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        print("=" * 72)
        print(f"Operations: {summary['operations']['total']}")
        print(f"Success: {summary['operations']['success']}")
        print(f"Failure: {summary['operations']['failure']}")
        print(
            "Success rate: "
            f"{summary['operations']['success_rate_percent']:.3f}%"
        )
        print(f"RSS delta: {summary['resources']['rss_delta_kib']} KiB")
        print(f"FD delta: {summary['resources']['fd_delta']}")
        print(f"Final 5V confirmed: {final_5v_confirmed}")
        print(f"USB closed: {usb_closed}")
        print(f"CSV log saved: {csv_path}")
        print(f"JSON summary saved: {json_path}")
        print("PASS" if summary["pass"] else "FAIL")
        print("=" * 72)

        if not summary["pass"] and return_code == 0:
            return_code = 1

    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
