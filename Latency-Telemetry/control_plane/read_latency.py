#!/usr/bin/env python3
import argparse
import datetime as dt
import re
import subprocess
import sys
import time
from typing import Dict, List

REGISTER_REGEX = re.compile(r"latency_reg\[(\d+)\]\s*=\s*(0x[0-9a-fA-F]+|[0-9]+)")


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


def parse_values(cli_output: str) -> Dict[int, int]:
    values: Dict[int, int] = {}
    for match in REGISTER_REGEX.finditer(cli_output):
        idx = int(match.group(1))
        raw_value = int(match.group(2), 0)
        values[idx] = raw_value
    return values


def read_latency_once(thrift_port: int, register_name: str, indices: List[int]) -> Dict[int, int]:
    commands = [f"register_read {register_name} {idx}" for idx in indices]
    output = run_cli(thrift_port, commands)
    parsed = parse_values(output)
    missing = [idx for idx in indices if idx not in parsed]
    if missing:
        raise RuntimeError(
            "Could not parse all register indices from CLI output. "
            f"Missing: {missing}\nRaw output:\n{output}"
        )
    return parsed


def fmt_line(index: int, ticks: int, tick_ms: float) -> str:
    latency_ms = ticks * tick_ms
    return f"index={index:>3d} raw_ticks={ticks:>12d} latency_ms={latency_ms:>12.3f}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Periodically read latency_reg from BMv2 and print in milliseconds."
    )
    parser.add_argument("--thrift-port", type=int, default=9090, help="BMv2 thrift port")
    parser.add_argument("--register", default="latency_reg", help="Register name")
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
    parser.add_argument(
        "--tick-ms",
        type=float,
        default=0.001,
        help="How many milliseconds each register tick represents",
    )
    parser.add_argument(
        "--tick-us",
        type=float,
        default=None,
        help=argparse.SUPPRESS,
    )

    args = parser.parse_args()

    try:
        indices = [int(x.strip()) for x in args.indices.split(",") if x.strip()]
    except ValueError as exc:
        raise SystemExit(f"Invalid --indices value: {args.indices}") from exc

    if not indices:
        raise SystemExit("At least one register index is required")

    tick_ms = args.tick_ms
    if args.tick_us is not None:
        # Backward compatibility: convert legacy microsecond flag to ms.
        tick_ms = args.tick_us / 1000.0

    print(
        "Polling register "
        f"{args.register} at thrift port {args.thrift_port} "
        f"every {args.interval:.2f}s (tick={tick_ms} ms)."
    )
    print("Press Ctrl+C to stop.\n")

    while True:
        ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            values = read_latency_once(args.thrift_port, args.register, indices)
            print(ts)
            for idx in indices:
                print("  " + fmt_line(idx, values[idx], tick_ms))
        except Exception as exc:  # pylint: disable=broad-except
            print(f"{ts} ERROR: {exc}", file=sys.stderr)

        print("")
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
