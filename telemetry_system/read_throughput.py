#!/usr/bin/env python3
"""Periodically read a byte-counter register from BMv2 and print throughput in bps.

This is modeled after read_latency.py but computes delta-bytes/time to report bps.
"""
import argparse
import datetime as dt
import re
import subprocess
import sys
import time
from typing import Dict, List


def run_cli(thrift_port: int, commands: List[str]) -> str:
    payload = "\n".join(commands) + "\n"
    proc = subprocess.run(
        ["simple_switch_CLI", "--thrift-port", str(thrift_port)],
        input=payload,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"simple_switch_CLI failed (port {thrift_port}). stderr:\n{proc.stderr}"
        )
    return proc.stdout


def parse_values(cli_output: str, register: str) -> Dict[int, int]:
    # expects lines like: throughput_reg[2] = 12345
    pattern = re.compile(rf"{re.escape(register)}\[(\d+)\]\s*=\s*(0x[0-9a-fA-F]+|[0-9]+)")
    values: Dict[int, int] = {}
    for match in pattern.finditer(cli_output):
        idx = int(match.group(1))
        raw_value = int(match.group(2), 0)
        values[idx] = raw_value
    return values


def read_register_once(thrift_port: int, register_name: str, indices: List[int]) -> Dict[int, int]:
    commands = [f"register_read {register_name} {idx}" for idx in indices]
    output = run_cli(thrift_port, commands)
    parsed = parse_values(output, register_name)
    missing = [idx for idx in indices if idx not in parsed]
    if missing:
        raise RuntimeError(
            "Could not parse all register indices from CLI output. "
            f"Missing: {missing}\nRaw output:\n{output}"
        )
    return parsed


def fmt_line(index: int, bytes_delta: int, seconds: float) -> str:
    bps = (bytes_delta * 8) / seconds if seconds > 0 else 0.0
    return f"index={index:>3d} bytes_delta={bytes_delta:>12d} interval_s={seconds:>8.3f} bps={bps:>12.3f}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Periodically read a byte counter register from BMv2 and print throughput in bps."
    )
    parser.add_argument("--thrift-port", type=int, default=9090, help="BMv2 thrift port")
    parser.add_argument("--register", default="throughput_reg", help="Register name")
    parser.add_argument(
        "--indices",
        default="2",
        help="Comma-separated register indices, e.g. 2 or 2,3",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Polling interval in seconds",
    )

    args = parser.parse_args()

    try:
        indices = [int(x.strip()) for x in args.indices.split(",") if x.strip()]
    except ValueError as exc:
        raise SystemExit(f"Invalid --indices value: {args.indices}") from exc

    if not indices:
        raise SystemExit("At least one register index is required")

    print(
        "Polling register "
        f"{args.register} at thrift port {args.thrift_port} "
        f"every {args.interval:.2f}s."
    )
    print("Press Ctrl+C to stop.\n")

    prev_values: Dict[int, int] = {}
    prev_ts = time.monotonic()

    # initial read to bootstrap previous values
    try:
        prev_values = read_register_once(args.thrift_port, args.register, indices)
    except Exception as exc:  # pylint: disable=broad-except
        print(f"Bootstrap read ERROR: {exc}", file=sys.stderr)
        return 1

    while True:
        time.sleep(args.interval)
        now_ts = time.monotonic()
        ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            current = read_register_once(args.thrift_port, args.register, indices)
            elapsed = now_ts - prev_ts
            print(ts)
            for idx in indices:
                delta = current[idx] - prev_values.get(idx, 0)
                print("  " + fmt_line(idx, delta, elapsed))
            prev_values = current
            prev_ts = now_ts
        except Exception as exc:  # pylint: disable=broad-except
            print(f"{ts} ERROR: {exc}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
