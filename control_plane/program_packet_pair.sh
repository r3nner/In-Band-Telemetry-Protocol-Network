#!/usr/bin/env bash

S1_COMMANDS='reset_state

# Existing IPv4 forwarding is kept so h1/h2 can still be used for regression tests.
table_add ipv4_lpm ipv4_forward 10.0.0.2/32 => 00:00:00:00:02:02 00:aa:00:00:01:02 2
table_add ipv4_lpm ipv4_forward 10.0.0.1/32 => 00:00:00:00:01:01 00:aa:00:00:01:01 1

# Packet-pair probe path: probe_s2 MAC always leaves S1 via port 2 toward S2.
table_add pair_l2_forward pair_forward 00:00:00:00:0A:02 => 00:00:00:00:0A:02 00:aa:00:00:01:01 2

# In-Band Capacity Probe Configuration
mirroring_add 253 2
table_add capacity_probe_forward clone_probe 0x1234 => 2 253
'

S2_COMMANDS='reset_state

table_add ipv4_lpm ipv4_forward 10.0.0.2/32 => 00:00:00:00:02:02 00:aa:00:00:02:02 2
table_add ipv4_lpm ipv4_forward 10.0.0.1/32 => 00:00:00:00:01:01 00:aa:00:00:02:01 1

# Packet-pair probe path: probe_s2 MAC leaves S2 via port 3 toward probe_s2.
table_add pair_l2_forward pair_forward 00:00:00:00:0A:02 => 00:00:00:00:0A:02 00:aa:00:00:02:02 3
'

echo "Programming S1..."
echo "$S1_COMMANDS" | simple_switch_CLI --thrift-port 9090

echo "Programming S2..."
echo "$S2_COMMANDS" | simple_switch_CLI --thrift-port 9091
