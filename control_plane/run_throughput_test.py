#!/usr/bin/env python3
"""Run a complete throughput test with Mininet, iperf, and the BMv2 counter poller."""
import argparse
import os
import pathlib
import subprocess
import sys
import time
from typing import Dict

ROOT = pathlib.Path(__file__).resolve().parents[1]
TOPOLOGIES = ROOT / "topologies"
CONTROL = ROOT / "control_plane"

if str(TOPOLOGIES) not in sys.path:
    sys.path.insert(0, str(TOPOLOGIES))

from linear_topo import build_net as build_linear_net  # noqa: E402
from triangle_topo import build_net as build_triangle_net  # noqa: E402


def run_program_script(script_name: str, env: Dict[str, str]) -> None:
    script_path = CONTROL / script_name
    result = subprocess.run(["sh", str(script_path)], env=env, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"{script_name} failed:\n{result.stdout}{result.stderr}")


def start_poller(thrift_port: int, indices: str, interval: float) -> subprocess.Popen:
    return subprocess.Popen(
        [
            sys.executable,
            str(CONTROL / "read_throughput.py"),
            "--thrift-port",
            str(thrift_port),
            "--indices",
            indices,
            "--interval",
            str(interval),
        ],
        text=True,
    )


def start_transmission_poller(thrift_port: int, indices: str, interval: float, link_bw_mbps: float) -> subprocess.Popen:
    return subprocess.Popen(
        [
            sys.executable,
            str(CONTROL / "read_transmission_delay.py"),
            "--thrift-port",
            str(thrift_port),
            "--indices",
            indices,
            "--interval",
            str(interval),
            "--link-bw-mbps",
            str(link_bw_mbps),
        ],
        text=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a throughput measurement demo with iperf and BMv2.")
    parser.add_argument("--topology", choices=("linear", "triangle"), default="linear")
    parser.add_argument("--json", required=True, help="Path to BMv2 JSON")
    parser.add_argument("--switch-bin", default="simple_switch", help="Path to simple_switch binary")
    parser.add_argument("--thrift-base", type=int, default=9090)
    parser.add_argument("--interval", type=float, default=1.0, help="Poll interval in seconds")
    parser.add_argument("--duration", type=int, default=10, help="iperf client duration in seconds")
    parser.add_argument("--probe-interval-us", type=int, default=200000, help="Telemetry probe interval for existing setup")
    parser.add_argument("--link-bw-mbps", type=float, default=10.0, help="Bandwidth used by Mininet links in Mbps")
    args = parser.parse_args()

    env = dict(os.environ)
    env["PROBE_INTERVAL_US"] = str(args.probe_interval_us)
    env["S1_THRIFT_PORT"] = str(args.thrift_base)
    env["S2_THRIFT_PORT"] = str(args.thrift_base + 1)
    if args.topology == "triangle":
        env["S3_THRIFT_PORT"] = str(args.thrift_base + 2)

    if args.topology == "linear":
        net = build_linear_net(args.json, args.switch_bin, args.thrift_base, args.link_bw_mbps)
        program_script = "program_linear.sh"
        poll_indices = "2,1"
        dst_ip = "10.0.0.2"
    else:
        net = build_triangle_net(args.json, args.switch_bin, args.thrift_base, args.link_bw_mbps)
        program_script = "program_triangle.sh"
        poll_indices = "2,3,1"
        dst_ip = "10.0.20.2"

    try:
        run_program_script(program_script, env)
        poller = start_poller(args.thrift_base, poll_indices, args.interval)
        tx_poller = start_transmission_poller(args.thrift_base, poll_indices, args.interval, args.link_bw_mbps)
        h1 = net.get("h1")
        h2 = net.get("h2")
        h2.cmd("iperf -s -D")
        time.sleep(1)
        try:
            h1.cmd(f"iperf -c {dst_ip} -t {args.duration}")
        finally:
            poller.terminate()
            poller.wait(timeout=10)
            tx_poller.terminate()
            tx_poller.wait(timeout=10)
        return 0
    finally:
        net.stop()


if __name__ == "__main__":
    raise SystemExit(main())
