#!/usr/bin/env python3
"""
Test link capacity using packet-pair dispersion.

This script runs the packet-pair capacity test in a coordinated way:
1. Starts the topology (packet_pair_topo.py)
2. Programs the switches (program_packet_pair.sh)
3. Starts the sniffer on probe_s2-eth0
4. Sends probes from probe_s1-eth0
5. Reports capacity in bps

Usage:
    sudo python3 control_plane/test_link_capacity.py \
        --json build/main.json \
        --probe-bw-mbps 1000 \
        --bottleneck-bw-mbps 10 \
        --frame-size 1500
"""
import argparse
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path


def run_command(cmd, description, shell=False, timeout=None):
    """Run a shell command and return output."""
    print(f"\n[INFO] {description}")
    print(f"[CMD] {cmd if isinstance(cmd, str) else ' '.join(cmd)}")
    try:
        result = subprocess.run(
            cmd,
            shell=shell,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            print(f"[STDERR] {result.stderr}")
        return result
    except subprocess.TimeoutExpired:
        print(f"[TIMEOUT] Command exceeded {timeout}s")
        return None
    except Exception as e:
        print(f"[ERROR] {e}")
        return None


def main():
    parser = argparse.ArgumentParser(
        description="Automated packet-pair capacity test.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test with 10 Mbps bottleneck
  sudo python3 control_plane/test_link_capacity.py \\
    --json build/main.json \\
    --bottleneck-bw-mbps 10

  # Test with custom frame size
  sudo python3 control_plane/test_link_capacity.py \\
    --json build/main.json \\
    --bottleneck-bw-mbps 100 \\
    --frame-size 500
        """,
    )
    parser.add_argument(
        "--json",
        required=True,
        help="Path to BMv2 JSON (usually build/main.json)",
    )
    parser.add_argument(
        "--probe-bw-mbps",
        type=float,
        default=1000.0,
        help="Bandwidth for probe links in Mbps (default 1000)",
    )
    parser.add_argument(
        "--bottleneck-bw-mbps",
        type=float,
        default=10.0,
        help="Bandwidth for bottleneck link in Mbps (default 10)",
    )
    parser.add_argument(
        "--frame-size",
        type=int,
        default=1500,
        help="Frame size for probes in bytes (default 1500)",
    )
    parser.add_argument(
        "--thrift-base",
        type=int,
        default=9090,
        help="Thrift base port (default 9090)",
    )
    args = parser.parse_args()

    ws = Path.cwd()
    json_path = ws / args.json
    if not json_path.exists():
        print(f"[ERROR] JSON file not found: {json_path}")
        return 1

    prog_script = ws / "control_plane" / "program_packet_pair.sh"
    if not prog_script.exists():
        print(f"[ERROR] Program script not found: {prog_script}")
        return 1

    # Step 1: Start topology
    topo_cmd = [
        "sudo",
        "python3",
        "topologies/packet_pair_topo.py",
        "--json",
        str(json_path),
        "--probe-bw-mbps",
        str(args.probe_bw_mbps),
        "--bottleneck-bw-mbps",
        str(args.bottleneck_bw_mbps),
        "--no-cli",
    ]
    result = run_command(topo_cmd, "Step 1: Starting packet-pair topology")
    if not result or result.returncode != 0:
        print("[ERROR] Failed to start topology")
        return 1

    # Give switches time to initialize
    print("\n[INFO] Waiting for switches to initialize...")
    time.sleep(2)

    # Step 2: Program switches
    prog_cmd = f"cd {ws} && bash {prog_script}"
    result = run_command(prog_cmd, "Step 2: Programming switch forwarding rules", shell=True)
    if not result or result.returncode != 0:
        print("[ERROR] Failed to program switches")
        return 1

    print("\n[INFO] Waiting for control plane to stabilize...")
    time.sleep(1)

    # Step 3: Start sniffer in background
    sniff_cmd = [
        "sudo",
        "python3",
        "control_plane/sniff_probes.py",
        "--iface",
        "probe_s2-eth0",
        "--timeout",
        "10",
    ]

    print("\n[INFO] Step 3: Starting packet sniffer on probe_s2-eth0...")
    sniff_proc = subprocess.Popen(
        sniff_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    # Give sniffer time to start listening
    time.sleep(0.5)

    # Step 4: Send probes
    send_cmd = [
        "sudo",
        "python3",
        "control_plane/send_probes.py",
        "--iface",
        "probe_s1-eth0",
        "--frame-size",
        str(args.frame_size),
    ]
    print("\n[INFO] Step 4: Sending back-to-back probes from probe_s1-eth0...")
    result = run_command(send_cmd, "Sending probes")

    # Step 5: Collect sniffer output
    print("\n[INFO] Step 5: Collecting capacity measurement...")
    try:
        sniff_stdout, _ = sniff_proc.communicate(timeout=12)
        print(sniff_stdout)
    except subprocess.TimeoutExpired:
        sniff_proc.kill()
        print("[WARNING] Sniffer timeout")

    print("\n" + "="*60)
    print("[DONE] Packet-pair capacity test completed")
    print("="*60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
