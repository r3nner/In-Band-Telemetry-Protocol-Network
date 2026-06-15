import argparse
import subprocess
import time
import sys


def run_command(cmd: list, desc: str) -> subprocess.CompletedProcess:
    print(f"\n[EXEC] {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[ERROR] {desc} failed. Exit code {result.returncode}")
        print(f"STDOUT:\n{result.stdout}")
        print(f"STDERR:\n{result.stderr}")
    else:
        print(f"[OK] {desc} succeeded.")
    return result


def get_mininet_host_pid(hostname: str) -> str:
    result = subprocess.run(["pgrep", "-f", f"mininet:{hostname}$"], capture_output=True, text=True)
    pids = result.stdout.strip().split()
    if not pids:
        # Fallback if pattern is slightly different
        result = subprocess.run(["pgrep", "-f", f"bash.*mininet:{hostname}"], capture_output=True, text=True)
        pids = result.stdout.strip().split()
        if not pids:
            raise RuntimeError(f"Mininet host '{hostname}' not found. Is Mininet running?")
    return pids[0]


def send_probe_from_host(hostname: str, frame_size: int, probe_id: int):
    pid = get_mininet_host_pid(hostname)
    cmd = [
        "nsenter", "-t", pid, "-n",
        "python3", "control_plane/send_probes.py",
        "--iface", f"{hostname}-eth0",
        "--frame-size", str(frame_size),
        "--probe-id", str(probe_id)
    ]
    run_command(cmd, f"Sending probe from {hostname}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Automated In-Band Link Capacity measurement (requires running Mininet)")
    parser.add_argument("--host", default="h1", help="Mininet host to inject the probe from (default: h1)")
    parser.add_argument("--probe-id", type=lambda x: int(x, 0), default=1, help="Probe ID (hex or int) to match the switch clone rule")
    parser.add_argument("--thrift-port", type=int, default=9091, help="Thrift port of the receiver switch to read the capacity from")
    parser.add_argument("--frame-size", type=int, default=1500, help="Size of probe packets")
    args = parser.parse_args()

    print("\n" + "="*60)
    print("Measuring Link Capacity via Packet-Pair...")
    print("="*60)
    
    try:
        # Step 1: Send single probe trigger
        print(f"\n[INFO] Step 1: Sending single capacity probe trigger from {args.host} (probe_id={hex(args.probe_id)})...")
        send_probe_from_host(args.host, args.frame_size, args.probe_id)

        # Step 2: Collect telemetry via Thrift
        print(f"\n[INFO] Step 2: Collecting capacity measurement from P4 register via Thrift (port {args.thrift_port})...")
        time.sleep(1)  # Give time for the probe to cross the network
        read_cmd = [
            "python3",
            "control_plane/read_link_capacity.py",
            "--thrift-port",
            str(args.thrift_port),
            "--frame-size",
            str(args.frame_size),
        ]
        result = run_command(read_cmd, "Reading link capacity")
        print("\n--- RESULTS ---")
        print(result.stdout)

    except Exception as e:
        print(f"\n[FATAL ERROR] {e}")
        sys.exit(1)

    print("\n" + "="*60)
    print("[DONE] Link Capacity measurement completed")
    print("="*60)

if __name__ == "__main__":
    main()
