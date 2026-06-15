import argparse
import sys
import json
import subprocess


def read_register(thrift_port: int, reg_name: str) -> list:
    cmd = f"echo 'register_read {reg_name}' | simple_switch_CLI --thrift-port {thrift_port}"
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        lines = result.stdout.splitlines()
        values = []
        # capacity_delta_reg= 0, 92310817, 0, 0, ...
        for line in lines:
            if f"{reg_name}=" in line:
                values_str = line.split(f"{reg_name}=")[1].strip()
                str_items = values_str.split(",")
                for item in str_items:
                    if item.strip():
                        values.append(int(item.strip()))
        return values
    except Exception as e:
        print(f"[ERROR] Failed to read register {reg_name}: {e}")
        return []


def main():
    parser = argparse.ArgumentParser(description="Read link capacity via Thrift")
    parser.add_argument("--thrift-port", type=int, required=True, help="Thrift port of the receiver switch")
    parser.add_argument("--frame-size", type=int, required=True, help="Size of probe packets in bytes")
    args = parser.parse_args()

    deltas = read_register(args.thrift_port, "capacity_delta_reg")
    
    if not deltas:
        print("[ERROR] Could not read capacity_delta_reg")
        sys.exit(1)

    found = False
    for port, delta_t in enumerate(deltas):
        if delta_t > 0:
            L_bits = args.frame_size * 8
            capacity_bps = (L_bits * 1e6) / delta_t
            capacity_mbps = capacity_bps / 1e6
            print(f"[REPORT] Port {port}: delta_t = {delta_t} us, Link Capacity = {capacity_bps:.2f} bps ({capacity_mbps:.2f} Mbps)")
            found = True

    if not found:
        print("[WARNING] No non-zero delta_t found in capacity_delta_reg. Ensure probes were sent and received.")


if __name__ == "__main__":
    main()
