#!/usr/bin/env bash
set -euo pipefail

# Programs S1/S2/S3 for triangle topology:
# H1 <-> S1 <-> S2 <-> S3 <-> H2 and S1 <-> S3
#
# S1 uses two mirror sessions:
#   session 250 -> port 2 (neighbor S2)
#   session 251 -> port 3 (neighbor S3)
#
# Todas as variáveis são lidas do config.json centralizado.
# Fallback para valores padrão caso o config.json não exista.

CONFIG_FILE="${CONFIG_FILE:-control_plane/config.json}"

# ---------------------------------------------------------------------------
# Leitura centralizada do config.json
# ---------------------------------------------------------------------------
if [ -f "${CONFIG_FILE}" ] && command -v python3 &>/dev/null; then
    read_config() {
        python3 -c "
import json, sys
with open('${CONFIG_FILE}') as f:
    cfg = json.load(f)
print(cfg.get('$1', '$2'))
"
    }
    S1_THRIFT_PORT="$(read_config s1_thrift_port 9090)"
    S2_THRIFT_PORT="$(read_config s2_thrift_port 9091)"
    S3_THRIFT_PORT="$(read_config s3_thrift_port 9092)"
    PROBE_INTERVAL_US="$(read_config probe_interval_us 1000000)"
    REPORT_INTERVAL_US="$(read_config report_interval_us 1000000)"
    CONTROLLER_IP="$(read_config controller_ip 10.0.0.254)"
else
    echo "[WARN] config.json não encontrado em '${CONFIG_FILE}', usando valores padrão."
    S1_THRIFT_PORT="9090"
    S2_THRIFT_PORT="9091"
    S3_THRIFT_PORT="9092"
    PROBE_INTERVAL_US="1000000"
    REPORT_INTERVAL_US="1000000"
    CONTROLLER_IP="10.0.0.254"
fi

echo "[INFO] Configuração carregada de: ${CONFIG_FILE}"
echo "  S1_THRIFT_PORT=${S1_THRIFT_PORT}"
echo "  S2_THRIFT_PORT=${S2_THRIFT_PORT}"
echo "  S3_THRIFT_PORT=${S3_THRIFT_PORT}"
echo "  PROBE_INTERVAL_US=${PROBE_INTERVAL_US}"
echo "  REPORT_INTERVAL_US=${REPORT_INTERVAL_US}"
echo "  CONTROLLER_IP=${CONTROLLER_IP}"
echo

# ---------------------------------------------------------------------------
# Conversão do IP do controlador para inteiro (usado nos registradores P4)
# ---------------------------------------------------------------------------
ip_to_int() {
    local ip="$1"
    local a b c d
    IFS='.' read -r a b c d <<< "${ip}"
    echo $(( (a << 24) + (b << 16) + (c << 8) + d ))
}
CONTROLLER_IP_INT="$(ip_to_int "${CONTROLLER_IP}")"

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

# IPs de origem dos switches
S1_IP_INT="$(ip_to_int 10.0.0.101)"
S2_IP_INT="$(ip_to_int 10.0.0.102)"
S3_IP_INT="$(ip_to_int 10.0.0.103)"

S1_COMMANDS="reset_state
mirroring_add 250 2
mirroring_add 251 3

# Route class A: force data path through S2
# S1->S2->S3->H2
table_add ipv4_lpm ipv4_forward 10.0.20.2/32 => 00:aa:00:00:02:01 00:aa:00:00:01:02 2

# Route class B: force data path directly through S3
# S1->S3->H2
table_add ipv4_lpm ipv4_forward 10.0.30.2/32 => 00:aa:00:00:03:01 00:aa:00:00:01:03 3

table_add ipv4_lpm ipv4_forward 10.0.0.1/32 => 00:00:00:00:01:01 00:aa:00:00:01:01 1

# Map each egress port to (register index, clone session)
table_add probe_profile enable_probe 2 => 2 1 250
table_add probe_profile enable_probe 3 => 3 1 251
register_write probe_interval_reg 2 ${PROBE_INTERVAL_US}
register_write probe_interval_reg 3 ${PROBE_INTERVAL_US}
register_write last_probe_ts_reg 2 0
register_write last_probe_ts_reg 3 0
register_write throughput_reg 2 0
register_write throughput_reg 3 0
register_write throughput_reg 1 0

# --- configuração de exportação de telemetria via UDP ---
register_write switch_id_reg 0 1
register_write switch_ip_reg 0 ${S1_IP_INT}
register_write controller_ip_reg 0 ${CONTROLLER_IP_INT}
mirroring_add 252 1
register_write report_interval_reg 2 ${REPORT_INTERVAL_US}
register_write last_report_ts_reg 2 0
register_write report_interval_reg 3 ${REPORT_INTERVAL_US}
register_write last_report_ts_reg 3 0
"

S2_COMMANDS="reset_state
mirroring_add 250 1
mirroring_add 251 2

table_add ipv4_lpm ipv4_forward 10.0.20.2/32 => 00:aa:00:00:03:02 00:aa:00:00:02:02 2
table_add ipv4_lpm ipv4_forward 10.0.30.2/32 => 00:aa:00:00:03:02 00:aa:00:00:02:02 2
table_add ipv4_lpm ipv4_forward 10.0.0.1/32  => 00:aa:00:00:01:02 00:aa:00:00:02:01 1

# egress 1 -> S1 (local idx 1, remote idx 2)
table_add probe_profile enable_probe 1 => 1 2 250
# egress 2 -> S3 (local idx 3, remote idx 2)
table_add probe_profile enable_probe 2 => 3 2 251
register_write probe_interval_reg 1 ${PROBE_INTERVAL_US}
register_write probe_interval_reg 3 ${PROBE_INTERVAL_US}
register_write last_probe_ts_reg 1 0
register_write last_probe_ts_reg 3 0
register_write throughput_reg 1 0
register_write throughput_reg 3 0

# --- configuração de exportação de telemetria via UDP ---
register_write switch_id_reg 0 2
register_write switch_ip_reg 0 ${S2_IP_INT}
register_write controller_ip_reg 0 ${CONTROLLER_IP_INT}
mirroring_add 252 1
register_write report_interval_reg 1 ${REPORT_INTERVAL_US}
register_write last_report_ts_reg 1 0
register_write report_interval_reg 2 ${REPORT_INTERVAL_US}
register_write last_report_ts_reg 2 0
"

S3_COMMANDS="reset_state
mirroring_add 250 1
mirroring_add 251 2
mirroring_add 252 3

table_add ipv4_lpm ipv4_forward 10.0.20.2/32 => 00:00:00:00:02:02 00:aa:00:00:03:03 3
table_add ipv4_lpm ipv4_forward 10.0.30.2/32 => 00:00:00:00:02:02 00:aa:00:00:03:03 3
table_add ipv4_lpm ipv4_forward 10.0.0.1/32  => 00:aa:00:00:01:03 00:aa:00:00:03:01 1

# egress 1 -> S1 (local idx 1, remote idx 3)
table_add probe_profile enable_probe 1 => 1 3 250
# egress 2 -> S2 (local idx 2, remote idx 3)
table_add probe_profile enable_probe 2 => 2 3 251
# egress 3 -> H2 (no probe)
table_add probe_profile no_probe 3 =>
register_write probe_interval_reg 1 ${PROBE_INTERVAL_US}
register_write probe_interval_reg 2 ${PROBE_INTERVAL_US}
register_write last_probe_ts_reg 1 0
register_write last_probe_ts_reg 2 0
register_write throughput_reg 1 0
register_write throughput_reg 2 0
register_write throughput_reg 3 0

# --- configuração de exportação de telemetria via UDP ---
register_write switch_id_reg 0 3
register_write switch_ip_reg 0 ${S3_IP_INT}
register_write controller_ip_reg 0 ${CONTROLLER_IP_INT}
mirroring_add 252 3
register_write report_interval_reg 1 ${REPORT_INTERVAL_US}
register_write last_report_ts_reg 1 0
register_write report_interval_reg 2 ${REPORT_INTERVAL_US}
register_write last_report_ts_reg 2 0
"

run_cli "${S1_THRIFT_PORT}" "s1" "${S1_COMMANDS}"
run_cli "${S2_THRIFT_PORT}" "s2" "${S2_COMMANDS}"
run_cli "${S3_THRIFT_PORT}" "s3" "${S3_COMMANDS}"

echo
echo "Triangle topology control plane loaded."
echo "Use python3 control_plane/cli.py para gerenciar a rede."
echo "Telemetry probe interval: ${PROBE_INTERVAL_US} us"
