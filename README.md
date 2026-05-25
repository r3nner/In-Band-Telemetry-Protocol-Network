# Latency-Telemetry

P4/BMv2/Mininet lab for active in-band latency telemetry.

This project estimates per-link latency by cloning selected IPv4 packets into telemetry probes, reflecting them on the neighbor switch, and storing round-trip derived values in data-plane registers.

It also estimates transmission delay as a software-derived metric using the packet length reported by BMv2 and the link bandwidth configured in Mininet.

It also includes a throughput path based on control-plane polling of byte counters, plus an experiment helper for running iperf inside the Mininet topology.

It now also includes a separate packet-pair dispersion experiment using out-of-band Scapy probes and a dedicated L2 forwarding path for telemetry `msg_type=2`.

## How It Works

1. Source switch clones selected IPv4 packets and emits telemetry probes.
2. Neighbor switch reflects probes and adds local processing time.
3. Source switch computes one-way estimate:

$$
latency = (t_{receive} - t_{send} - t_{proc}) / 2
$$

4. Latency is written to `latency_reg[index]` and mirrored as a report to keep both peers synchronized.

5. Transmission delay is computed in the control plane from:

$$
d_{trans} = \frac{L}{R}
$$

where `L` comes from `packet_length_reg[index]` and `R` comes from the `TCLink` bandwidth configured for the path.

## Repository Layout

- `p4/main.p4`: P4_16 v1model data plane.
- `scripts/setup_ubuntu.sh`: full Ubuntu bootstrap (PI, BMv2, p4c, Mininet, Python deps).
- `scripts/health_check.sh`: verifies toolchain, compilation, Python imports, and Mininet smoke test.
- `scripts/build_p4.sh`: builds `p4/main.p4` into `build/main.json`.
- `topologies/p4_mininet.py`: BMv2 Mininet integration classes.
- `topologies/linear_topo.py`: linear topology `h1-s1-s2-h2`.
- `topologies/triangle_topo.py`: triangle topology with two S1 egress paths.
- `topologies/packet_pair_topo.py`: linear packet-pair topology with `probe_s1` and `probe_s2`.
- `control_plane/program_linear.sh`: programs linear routing + mirroring.
- `control_plane/program_triangle.sh`: programs triangle routing + mirroring.
- `control_plane/program_packet_pair.sh`: programs the packet-pair probe path.
- `control_plane/read_latency.py`: polls latency registers over thrift.
- `control_plane/read_throughput.py`: polls throughput counters over thrift and prints bps from byte deltas.
- `control_plane/read_transmission_delay.py`: polls packet-length registers over thrift and derives transmission delay from link bandwidth.
- `control_plane/run_throughput_test.py`: runs an end-to-end iperf throughput demo.
- `control_plane/send_probes.py`: Scapy sender for back-to-back packet-pair probes.
- `control_plane/sniff_probes.py`: Scapy receiver that timestamps two probe arrivals and computes capacity.
- `build/main.json`: generated BMv2 JSON artifact.

## Prerequisites

- Ubuntu Linux.
- `sudo` access.
- Internet access to clone/build dependencies.

## Quick Start

1. Bootstrap environment (first time only):

```bash
chmod +x scripts/setup_ubuntu.sh
./scripts/setup_ubuntu.sh
```

2. Validate environment:

```bash
chmod +x scripts/health_check.sh scripts/build_p4.sh
./scripts/health_check.sh
```

3. Compile P4:

```bash
./scripts/build_p4.sh
```

## Transmission Delay

The Mininet links already use `TCLink`. To make transmission delay reproducible, the topology scripts now accept `--link-bw-mbps` and apply that value to every link in the topology.

Example for the linear topology:

```bash
sudo python3 topologies/linear_topo.py --json build/main.json --link-bw-mbps 10
```

After programming the switch, read the transmission delay estimate with:

```bash
python3 control_plane/read_transmission_delay.py --thrift-port 9090 --indices 2 --link-bw-mbps 10
```

The control plane reads `packet_length_reg`, converts bytes to bits, and computes `L/R` in software. The value is an analytical estimate, not a hardware-timed measurement from BMv2.

## Run: Linear Topology

1. Start Mininet topology:

```bash
sudo python3 topologies/linear_topo.py --json build/main.json
```

2. In Mininet CLI, program switches and send traffic:

```bash
PROBE_INTERVAL_US=200000 sh ./control_plane/program_linear.sh
h1 ping -c 5 10.0.0.2
```

3. In another terminal, read latency register:

```bash
python3 control_plane/read_latency.py --thrift-port 9090 --indices 2
```

### Throughput test

Run the automated throughput demo from the host:

```bash
sudo python3 control_plane/run_throughput_test.py --topology linear --json build/main.json --link-bw-mbps 10
```

This starts iperf on `h2`, runs an iperf client on `h1`, and polls `throughput_reg` during the traffic burst.
It also polls `packet_length_reg` to report transmission delay estimates for the monitored indices.

## Run: Triangle Topology

1. Start Mininet topology:

```bash
sudo python3 topologies/triangle_topo.py --json build/main.json
```

2. In Mininet CLI, program switches and test both route classes:

```bash
PROBE_INTERVAL_US=200000 sh ./control_plane/program_triangle.sh
h1 ping -c 5 10.0.20.2
h1 ping -c 5 10.0.30.2
```

3. In another terminal, read both tracked indices:

```bash
python3 control_plane/read_latency.py --thrift-port 9090 --indices 2,3
```

### Throughput test

Run the automated throughput demo from the host:

```bash
sudo python3 control_plane/run_throughput_test.py --topology triangle --json build/main.json --link-bw-mbps 10
```

The helper programs the switch, starts the traffic burst, and reads the per-index throughput counters in parallel.
It also derives transmission delay from the configured link bandwidth and the last packet length seen by each monitored index.

## Run: Packet-Pair Capacity Test

1. Start the dedicated topology:

```bash
sudo python3 topologies/packet_pair_topo.py --json build/main.json --probe-bw-mbps 1000 --bottleneck-bw-mbps 10
```

2. In Mininet CLI, load the probe forwarding rules:

```bash
sh ./control_plane/program_packet_pair.sh
```

3. Start the receiver first on the probe host attached to S2:

```bash
sudo python3 control_plane/sniff_probes.py --iface probe_s2-eth0
```

4. Send the back-to-back probes from the host attached to S1:

```bash
sudo python3 control_plane/send_probes.py --iface probe_s1-eth0
```

The receiver logs the arrival of packet 1 and packet 2, computes `delta_t`, and prints the estimated capacity in bps using `bits / delta_t`.

## Configuration

- `PROBE_INTERVAL_US`: probe emission interval in microseconds.
- `PROBE_INTERVAL_US=0`: probe every eligible packet.
- `--link-bw-mbps`: Mininet bandwidth used to model transmission delay.
- `--probe-bw-mbps`: bandwidth for the packet-pair probe links.
- `--bottleneck-bw-mbps`: bandwidth for the packet-pair inter-switch bottleneck.
- Default thrift ports:
  - `s1=9090`
  - `s2=9091`
  - `s3=9092`

Example:

```bash
PROBE_INTERVAL_US=500000 sh ./control_plane/program_triangle.sh
```

## Troubleshooting

- No telemetry values changing:
  - Verify control-plane script completed without CLI errors.
  - Confirm mirror sessions are configured (`mirroring_add`) on each switch.
  - Check that traffic is actually traversing monitored egress ports.

- `simple_switch_CLI` fails right after topology boot:
  - Retry after a short delay; scripts already include thrift readiness checks.

- Register output remains zero:
  - Ensure pings target the addresses programmed in route tables.
  - Reduce `PROBE_INTERVAL_US` to increase probe frequency.

## Notes

`build/main.json` is generated. Rebuild after changing `p4/main.p4`:

```bash
./scripts/build_p4.sh
```
