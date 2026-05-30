#!/usr/bin/env bash
set -euo pipefail

# Programs S1/S2 for linear topology:
# H1 <-> S1 <-> S2 <-> H2
#
# Default thrift ports follow topologies/linear_topo.py.

S1_THRIFT_PORT="${S1_THRIFT_PORT:-9090}"
S2_THRIFT_PORT="${S2_THRIFT_PORT:-9091}"
PROBE_INTERVAL_US="${PROBE_INTERVAL_US:-1000000}"

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
mirroring_add 250 2

table_add ipv4_lpm ipv4_forward 10.0.0.2/32 => 00:00:00:00:02:02 00:aa:00:00:01:02 2
table_add ipv4_lpm ipv4_forward 10.0.0.1/32 => 00:00:00:00:01:01 00:aa:00:00:01:01 1

table_add probe_profile enable_probe 2 => 2 1 250
register_write probe_interval_reg 2 __PROBE_INTERVAL_US__
register_write last_probe_ts_reg 2 0
register_write throughput_reg 2 0
register_write throughput_reg 1 0

# --- configuração de exportação de telemetria via UDP ---
# ID único do switch S1
register_write switch_id_reg 0 1
# IP de origem do switch S1 (10.0.0.101 = 167772261)
register_write switch_ip_reg 0 167772261
# IP do controlador (10.0.0.254 = 167772414)
register_write controller_ip_reg 0 167772414
# Sessão de clone para reports UDP — porta 1 (host side)
mirroring_add 252 1
# Intervalo de report de throughput para porta monitorada 2 (1 segundo)
register_write report_interval_reg 2 1000000
# Último timestamp de report para porta monitorada 2
register_write last_report_ts_reg 2 0
'

S2_COMMANDS='reset_state
mirroring_add 250 1

table_add ipv4_lpm ipv4_forward 10.0.0.2/32 => 00:00:00:00:02:02 00:aa:00:00:02:02 2
table_add ipv4_lpm ipv4_forward 10.0.0.1/32 => 00:00:00:00:01:01 00:aa:00:00:02:01 1

table_add probe_profile enable_probe 1 => 1 2 250
register_write probe_interval_reg 1 __PROBE_INTERVAL_US__
register_write last_probe_ts_reg 1 0
register_write throughput_reg 1 0
register_write throughput_reg 2 0

# --- configuração de exportação de telemetria via UDP ---
# ID único do switch S2
register_write switch_id_reg 0 2
# IP de origem do switch S2 (10.0.0.102 = 167772262)
register_write switch_ip_reg 0 167772262
# IP do controlador (10.0.0.254 = 167772414)
register_write controller_ip_reg 0 167772414
# Sessão de clone para reports UDP — porta 2 (host side)
mirroring_add 252 2
# Intervalo de report de throughput para porta monitorada 1 (1 segundo)
register_write report_interval_reg 1 1000000
# Último timestamp de report para porta monitorada 1
register_write last_report_ts_reg 1 0
'

S1_COMMANDS="${S1_COMMANDS//__PROBE_INTERVAL_US__/${PROBE_INTERVAL_US}}"
S2_COMMANDS="${S2_COMMANDS//__PROBE_INTERVAL_US__/${PROBE_INTERVAL_US}}"

run_cli "${S1_THRIFT_PORT}" "s1" "${S1_COMMANDS}"
run_cli "${S2_THRIFT_PORT}" "s2" "${S2_COMMANDS}"

echo

echo "Linear topology control plane loaded."
echo "Use python3 control_plane/read_latency.py --thrift-port ${S1_THRIFT_PORT} --indices 2"
echo "Telemetry probe interval: ${PROBE_INTERVAL_US} us"
