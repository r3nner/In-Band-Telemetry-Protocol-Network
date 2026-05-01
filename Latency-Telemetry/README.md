# Latency-Telemetry

P4/BMv2/Mininet lab for active in-band latency telemetry.

This project estimates per-link latency by cloning selected IPv4 packets into telemetry probes, reflecting them on the neighbor switch, and storing round-trip derived values in data-plane registers.

## How It Works

1. Source switch clones selected IPv4 packets and emits telemetry probes.
2. Neighbor switch reflects probes and adds local processing time.
3. Source switch computes one-way estimate:

$$
latency = (t_{receive} - t_{send} - t_{proc}) / 2
$$

4. Latency is written to `latency_reg[index]` and mirrored as a report to keep both peers synchronized.

## Repository Layout

- `p4/main.p4`: P4_16 v1model data plane.
- `scripts/setup_ubuntu.sh`: full Ubuntu bootstrap (PI, BMv2, p4c, Mininet, Python deps).
- `scripts/health_check.sh`: verifies toolchain, compilation, Python imports, and Mininet smoke test.
- `scripts/build_p4.sh`: builds `p4/main.p4` into `build/main.json`.
- `topologies/p4_mininet.py`: BMv2 Mininet integration classes.
- `topologies/linear_topo.py`: linear topology `h1-s1-s2-h2`.
- `topologies/triangle_topo.py`: triangle topology with two S1 egress paths.
- `control_plane/program_linear.sh`: programs linear routing + mirroring.
- `control_plane/program_triangle.sh`: programs triangle routing + mirroring.
- `control_plane/read_latency.py`: polls latency registers over thrift.
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

## Configuration

- `PROBE_INTERVAL_US`: probe emission interval in microseconds.
- `PROBE_INTERVAL_US=0`: probe every eligible packet.
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
