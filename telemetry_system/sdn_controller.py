import subprocess
import time
import csv
import sys

def run_thrift_command(thrift_port: int, cmd: str) -> str:
    full_cmd = f"echo '{cmd}' | simple_switch_CLI --thrift-port {thrift_port}"
    try:
        result = subprocess.run(full_cmd, shell=True, capture_output=True, text=True)
        return result.stdout
    except Exception as e:
        return ""

def read_register(thrift_port: int, reg_name: str) -> list:
    stdout = run_thrift_command(thrift_port, f"register_read {reg_name}")
    values = []
    for line in stdout.splitlines():
        if f"{reg_name}=" in line:
            values_str = line.split(f"{reg_name}=")[1].strip()
            for item in values_str.split(","):
                if item.strip():
                    values.append(int(item.strip()))
    return values

def build_digital_twin():
    print("[INFO] Starting Topology Discovery & Digital Twin Export...")
    
    # We assume S1 is the root and uses Thrift 9090
    visited_switches = set()
    queue = [(1, 9090)]  # (switch_id, thrift_port)
    
    topology_edges = []
    metrics_data = []

    # Map of Switch ID to Thrift Port (assuming sequential starting from 9090)
    def get_thrift_port(switch_id):
        return 9090 + switch_id - 1

    while queue:
        current_id, thrift_port = queue.pop(0)
        
        if current_id in visited_switches:
            continue
            
        visited_switches.add(current_id)
        print(f"[INFO] Connecting to Switch {current_id} (Thrift: {thrift_port})")
        
        # Read neighbor table (register)
        neighbors = read_register(thrift_port, "neighbor_id_reg")
        latencies = read_register(thrift_port, "latency_reg")
        throughputs = read_register(thrift_port, "throughput_reg")
        capacities = read_register(thrift_port, "capacity_delta_reg")
        # For queue depth, we'd need to extract it, but for now we focus on the core metrics
        
        for port, neighbor_id in enumerate(neighbors):
            if neighbor_id != 0:
                print(f"  -> Found Link: S{current_id} (Port {port}) ---> S{neighbor_id}")
                topology_edges.append((current_id, port, neighbor_id))
                
                # Fetch metrics for this link
                latency = latencies[port] if port < len(latencies) else 0
                throughput = throughputs[port] if port < len(throughputs) else 0
                capacity_delta = capacities[port] if port < len(capacities) else 0
                
                # Convert Capacity Delta to Mbps
                cap_mbps = 0.0
                if capacity_delta > 0:
                    cap_mbps = ((1500 * 8 * 1e6) / capacity_delta) / 1e6

                metrics_data.append({
                    "Timestamp": int(time.time()),
                    "Source_Switch": f"S{current_id}",
                    "Source_Port": port,
                    "Target_Switch": f"S{neighbor_id}",
                    "Latency_us": latency,
                    "Capacity_mbps": round(cap_mbps, 2),
                    "Throughput_bps": throughput,
                    "Queue_Depth": 0
                })
                
                # Add neighbor to BFS queue
                if neighbor_id not in visited_switches:
                    queue.append((neighbor_id, get_thrift_port(neighbor_id)))

    # Export to CSV
    csv_file = "network_state.csv"
    if metrics_data:
        keys = metrics_data[0].keys()
        with open(csv_file, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(metrics_data)
        print(f"\n[OK] Digital Twin exported to {csv_file}")
    else:
        print("\n[WARNING] No links discovered.")

if __name__ == "__main__":
    build_digital_twin()
