#!/usr/bin/env bash
set -euo pipefail

# Programs S1/S2/S3 for triangle topology:
# H1 <-> S1 <-> S2 <-> S3 <-> H2 and S1 <-> S3
#
# S1 uses two mirror sessions:
#   session 250 -> port 2 (neighbor S2)
#   session 251 -> port 3 (neighbor S3)

S1_THRIFT_PORT="${S1_THRIFT_PORT:-9090}"
S2_THRIFT_PORT="${S2_THRIFT_PORT:-9091}"
S3_THRIFT_PORT="${S3_THRIFT_PORT:-9092}"
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
register_write probe_interval_reg 2 __PROBE_INTERVAL_US__
register_write probe_interval_reg 3 __PROBE_INTERVAL_US__
register_write last_probe_ts_reg 2 0
register_write last_probe_ts_reg 3 0
'

S2_COMMANDS='reset_state
mirroring_add 250 1
mirroring_add 251 2

table_add ipv4_lpm ipv4_forward 10.0.20.2/32 => 00:aa:00:00:03:02 00:aa:00:00:02:02 2
table_add ipv4_lpm ipv4_forward 10.0.30.2/32 => 00:aa:00:00:03:02 00:aa:00:00:02:02 2
table_add ipv4_lpm ipv4_forward 10.0.0.1/32  => 00:aa:00:00:01:02 00:aa:00:00:02:01 1

# egress 1 -> S1 (local idx 1, remote idx 2)
table_add probe_profile enable_probe 1 => 1 2 250
# egress 2 -> S3 (local idx 3, remote idx 2)
table_add probe_profile enable_probe 2 => 3 2 251
register_write probe_interval_reg 1 __PROBE_INTERVAL_US__
register_write probe_interval_reg 3 __PROBE_INTERVAL_US__
register_write last_probe_ts_reg 1 0
register_write last_probe_ts_reg 3 0
'

S3_COMMANDS='reset_state
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
register_write probe_interval_reg 1 __PROBE_INTERVAL_US__
register_write probe_interval_reg 2 __PROBE_INTERVAL_US__
register_write last_probe_ts_reg 1 0
register_write last_probe_ts_reg 2 0
'

S1_COMMANDS="${S1_COMMANDS//__PROBE_INTERVAL_US__/${PROBE_INTERVAL_US}}"
S2_COMMANDS="${S2_COMMANDS//__PROBE_INTERVAL_US__/${PROBE_INTERVAL_US}}"
S3_COMMANDS="${S3_COMMANDS//__PROBE_INTERVAL_US__/${PROBE_INTERVAL_US}}"

run_cli "${S1_THRIFT_PORT}" "s1" "${S1_COMMANDS}"
run_cli "${S2_THRIFT_PORT}" "s2" "${S2_COMMANDS}"
run_cli "${S3_THRIFT_PORT}" "s3" "${S3_COMMANDS}"

echo

echo "Triangle topology control plane loaded."
echo "Use python3 control_plane/read_latency.py --thrift-port ${S1_THRIFT_PORT} --indices 2,3"
echo "Telemetry probe interval: ${PROBE_INTERVAL_US} us"
