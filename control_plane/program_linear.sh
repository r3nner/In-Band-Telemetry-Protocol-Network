#!/usr/bin/env bash
set -euo pipefail

# Programs S1/S2 for linear topology:
# H1 <-> S1 <-> S2 <-> H2
#
# Todas as variáveis são lidas do config.json centralizado.
# Fallback para valores padrão caso o config.json não exista.

CONFIG_FILE="${CONFIG_FILE:-control_plane/config.json}"



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

S1_THRIFT_PORT="9090"
S2_THRIFT_PORT="9091"
PROBE_INTERVAL_US="1000000"

S1_COMMANDS="reset_state
mirroring_add 250 2

table_add ipv4_lpm ipv4_forward 10.0.0.2/32 => 00:00:00:00:02:02 00:aa:00:00:01:02 2
table_add ipv4_lpm ipv4_forward 10.0.0.1/32 => 00:00:00:00:01:01 00:aa:00:00:01:01 1

table_add probe_profile enable_probe 2 => 2 1 250
register_write probe_interval_reg 2 ${PROBE_INTERVAL_US}
register_write last_probe_ts_reg 2 0
register_write throughput_reg 2 0
register_write throughput_reg 1 0

# In-Band Capacity Probe Configuration (S1 -> S2)
mirroring_add 253 2
table_add capacity_probe_forward clone_probe 1 => 2 253
"

S2_COMMANDS="reset_state
mirroring_add 250 1

table_add ipv4_lpm ipv4_forward 10.0.0.2/32 => 00:00:00:00:02:02 00:aa:00:00:02:02 2
table_add ipv4_lpm ipv4_forward 10.0.0.1/32 => 00:00:00:00:01:01 00:aa:00:00:02:01 1

table_add probe_profile enable_probe 1 => 1 2 250
register_write probe_interval_reg 1 ${PROBE_INTERVAL_US}
register_write last_probe_ts_reg 1 0
register_write throughput_reg 1 0
register_write throughput_reg 2 0

# In-Band Capacity Probe Configuration (S2 -> S1 se quisermos testar reverso)
mirroring_add 253 1
table_add capacity_probe_forward clone_probe 0x1235 => 1 253
"

run_cli "${S1_THRIFT_PORT}" "s1" "${S1_COMMANDS}"
run_cli "${S2_THRIFT_PORT}" "s2" "${S2_COMMANDS}"

echo
echo "Linear topology programmed."
