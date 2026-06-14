#!/usr/bin/env bash
set -euo pipefail

# Programs S1 and S2 with base SDN configurations (Switch ID and Multicast for Flood)

S1_THRIFT_PORT="9090"
S2_THRIFT_PORT="9091"

run_cli() {
    local thrift_port="$1"
    local label="$2"
    local commands="$3"

    echo "[INFO] Programming ${label} (thrift ${thrift_port})"
    if ! printf "%s\n" "${commands}" | simple_switch_CLI --thrift-port "${thrift_port}" >/dev/null 2>&1; then
        echo "[ERROR] Failed to program ${label}."
    fi
}

# S1 Config: switch_id = 1, mcast_grp 1 = flood to ports 1, 2
S1_COMMANDS="reset_state
table_add node_info set_switch_id => 1
mc_mgrp_create 1
mc_node_create 1 1 2
mc_node_associate 1 1

table_add ipv4_lpm ipv4_forward 10.0.0.2/32 => 00:00:00:00:02:02 00:aa:00:00:01:02 2
table_add ipv4_lpm ipv4_forward 10.0.0.1/32 => 00:00:00:00:01:01 00:aa:00:00:01:01 1
"

# S2 Config: switch_id = 2, mcast_grp 1 = flood to ports 1, 2
S2_COMMANDS="reset_state
table_add node_info set_switch_id => 2
mc_mgrp_create 1
mc_node_create 2 1 2
mc_node_associate 1 2

table_add ipv4_lpm ipv4_forward 10.0.0.2/32 => 00:00:00:00:02:02 00:aa:00:00:02:02 2
table_add ipv4_lpm ipv4_forward 10.0.0.1/32 => 00:00:00:00:01:01 00:aa:00:00:02:01 1
"

run_cli "${S1_THRIFT_PORT}" "s1" "${S1_COMMANDS}"
run_cli "${S2_THRIFT_PORT}" "s2" "${S2_COMMANDS}"

echo "[OK] SDN switches initialized."
