#!/usr/bin/env python3
import subprocess
import re
import sys

def run_cli(thrift_port, command):
    cmd = f"echo '{command}' | simple_switch_CLI --thrift-port {thrift_port}"
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=2)
        return result.stdout
    except Exception as e:
        return ""

def get_active_ports(thrift_port):
    output = run_cli(thrift_port, "show_ports")
    if not output or "Connection refused" in output or "Could not connect to thrift client" in output:
        return None
    
    ports = []
    # Parse lines like "    1           s1-eth1           UP    "
    for line in output.split('\n'):
        line = line.strip()
        if re.match(r'^\d+\s+', line):
            parts = line.split()
            port_num = int(parts[0])
            if port_num > 0: # Ignore port 0 (loopback/cpu)
                ports.append(port_num)
    return ports

def deploy_telemetry_to_switch(thrift_port, ports):
    print(f"[INFO] Deploying Telemetry to Switch at Thrift {thrift_port}. Active ports: {ports}")
    
    commands = [
        "mc_mgrp_create 1"
    ]
    
    # Create a node mapping all active ports
    port_str = " ".join(map(str, ports))
    if ports:
        commands.append(f"mc_node_create 1 {port_str}")
        # Robustly associate multiple possible handles (simple_switch_CLI quirk)
        for handle in range(5):
            commands.append(f"mc_node_associate 1 {handle}")
            
    full_cmd = "\n".join(commands)
    
    process = subprocess.Popen(
        ["simple_switch_CLI", "--thrift-port", str(thrift_port)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    process.communicate(input=full_cmd)

def main():
    print("==================================================")
    print("      TELEMETRY DEPLOYMENT (PIGGYBACKING)         ")
    print("==================================================")
    
    switches_found = 0
    
    # Scan standard thrift ports
    for port in range(9090, 9100):
        ports = get_active_ports(port)
        if ports is not None:
            deploy_telemetry_to_switch(port, ports)
            switches_found += 1
            
    if switches_found == 0:
        print("[WARNING] No P4 switches found on management ports 9090-9099.")
    else:
        print(f"[OK] Telemetry Multicast successfully deployed to {switches_found} switches.")

if __name__ == "__main__":
    main()
