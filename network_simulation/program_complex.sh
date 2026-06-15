#!/usr/bin/env bash
set -euo pipefail

wait_for_thrift() {
    local thrift_port="$1"
    for ((i = 1; i <= 40; i++)); do
        if printf "show_tables\n" | simple_switch_CLI --thrift-port "${thrift_port}" >/dev/null 2>&1; then
            return 0
        fi
        sleep 0.5
    done
    return 1
}

run_cli() {
    local thrift_port="$1"
    local commands="$2"
    wait_for_thrift "${thrift_port}"
    printf "%s\n" "${commands}" | simple_switch_CLI --thrift-port "${thrift_port}" >/dev/null 2>&1
}

# S1
S1_CMDS="reset_state
table_set_default node_info set_switch_id 1
table_add ipv4_lpm ipv4_forward 10.0.0.1/32 => 00:00:00:00:01:01 00:aa:00:00:01:01 1
table_add ipv4_lpm ipv4_forward 10.0.0.2/32 => 00:00:00:00:02:02 00:aa:00:00:01:02 2
"
run_cli "9090" "${S1_CMDS}"

# S2
S2_CMDS="reset_state
table_set_default node_info set_switch_id 2
table_add ipv4_lpm ipv4_forward 10.0.0.1/32 => 00:00:00:00:01:01 00:aa:00:00:02:01 1
table_add ipv4_lpm ipv4_forward 10.0.0.2/32 => 00:00:00:00:02:02 00:aa:00:00:02:02 3
"
run_cli "9091" "${S2_CMDS}"

# S3
S3_CMDS="reset_state
table_set_default node_info set_switch_id 3
"
run_cli "9092" "${S3_CMDS}"

# S4
S4_CMDS="reset_state
table_set_default node_info set_switch_id 4
"
run_cli "9093" "${S4_CMDS}"

# S5
S5_CMDS="reset_state
table_set_default node_info set_switch_id 5
table_add ipv4_lpm ipv4_forward 10.0.0.1/32 => 00:00:00:00:01:01 00:aa:00:00:05:01 1
table_add ipv4_lpm ipv4_forward 10.0.0.2/32 => 00:00:00:00:02:02 00:aa:00:00:05:02 3
"
run_cli "9094" "${S5_CMDS}"

echo "Complex topology programmed with basic routes (S1-S2-S5) and IDs."
