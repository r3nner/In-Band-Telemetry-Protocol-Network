#!/usr/bin/env bash
set -euo pipefail

# Programs the packet-pair topology for out-of-band probes.
#
# Topology:
#   H1 <-> S1 <-> S2 <-> H2
#   probe_s1 <-> S1
#   probe_s2 <-> S2
#
# Probe frames use EtherType 0x88B5 and msg_type=2.

S1_THRIFT_PORT="${S1_THRIFT_PORT:-9090}"
S2_THRIFT_PORT="${S2_THRIFT_PORT:-9091}"

wait_for_thrift() {
    local thrift_port="$1"
    local retries="${2:-40}"

    for ((i = 1; i <= retries; i++)); do
        if printf "show_tables\n" | simple_switch_CLI --thrift-port "${thrift_port}" >/dev/null 2>&1; then
            return 0
        fi
        sleep 0.5
    done

    echo "[ERROR] Thrift port ${thrift_port} did not become ready in time"
    return 1
}

run_cli() {
    local thrift_port="$1"
    local label="$2"
    local commands="$3"

    echo "[INFO] Programming ${label} (thrift ${thrift_port})"
    wait_for_thrift "${thrift_port}"
    if ! printf "%s\n" "${commands}" | simple_switch_CLI --thrift-port "${thrift_port}" >/tmp/${label}_cli.log 2>&1; then
        echo "[ERROR] Failed to program ${label}. CLI output:"
        cat "/tmp/${label}_cli.log"
        exit 1
    fi
    echo "[OK] ${label} programmed"
}

S1_COMMANDS='reset_state

# Existing IPv4 forwarding is kept so h1/h2 can still be used for regression tests.
table_add ipv4_lpm ipv4_forward 10.0.0.2/32 => 00:00:00:00:02:02 00:aa:00:00:01:02 2
table_add ipv4_lpm ipv4_forward 10.0.0.1/32 => 00:00:00:00:01:01 00:aa:00:00:01:01 1

# Packet-pair probe path: probe_s2 MAC always leaves S1 via port 2 toward S2.
table_add pair_l2_forward pair_forward 00:00:00:00:0A:02 => 00:aa:00:00:01:02 00:aa:00:00:01:01 2
'

S2_COMMANDS='reset_state

table_add ipv4_lpm ipv4_forward 10.0.0.2/32 => 00:00:00:00:02:02 00:aa:00:00:02:02 2
table_add ipv4_lpm ipv4_forward 10.0.0.1/32 => 00:00:00:00:01:01 00:aa:00:00:02:01 1

# Packet-pair probe path: probe_s2 MAC leaves S2 via port 3 toward probe_s2.
table_add pair_l2_forward pair_forward 00:00:00:00:0A:02 => 00:aa:00:00:02:03 00:aa:00:00:02:02 3
'

run_cli "${S1_THRIFT_PORT}" "s1" "${S1_COMMANDS}"
run_cli "${S2_THRIFT_PORT}" "s2" "${S2_COMMANDS}"

echo

echo "Packet-pair control plane loaded."
echo "Start the receiver first: sudo python3 control_plane/sniff_probes.py --iface probe_s2-eth0"
echo "Then transmit: sudo python3 control_plane/send_probes.py --iface probe_s1-eth0"
