# In-Band Telemetry — SDN Ecosystem

P4/BMv2/Mininet laboratory for active in-band telemetry of latency, throughput, transmission delay, and link capacity (packet-pair), without the need for a database or centralized CLI.

## Simplified Architecture

1. The P4 switch intercepts frames or clones probes to calculate telemetry in the Data Plane.
2. The results (times, bytes, lengths) are stored in native P4 `registers` (SRAM).
3. Independent Python scripts query these `registers` via Thrift (BMv2 standard API) in a decoupled manner, calculate the metric, and display it on the screen.

## Repository Layout

├── Dockerfile / docker-compose.yml    # Ready-to-use Docker environment
├── p4/main.p4                         # P4_16 v1model data plane
├── scripts/
│   ├── setup_ubuntu.sh                # Bootstrap (PI, BMv2, p4c, Mininet)
│   ├── health_check.sh                # Toolchain verification
│   └── build_p4.sh                    # Compiles main.p4 → build/main.json
├── topologies/
│   ├── p4_mininet.py                  # BMv2 + Mininet integration
│   ├── linear_topo.py                 # h1-s1-s2-h2
│   ├── triangle_topo.py               # h1-s1-s2-s3-h2 + s1-s3
│   └── packet_pair_topo.py            # Packet-pair dispersion
├── control_plane/
│   ├── program_linear.sh              # Programs switches (linear topology)
│   ├── program_triangle.sh            # Programs switches (triangular topology)
│   ├── program_packet_pair.sh         # Programs packet-pair probes
│   ├── read_latency.py                # Latency register reader
│   ├── read_throughput.py             # Throughput counter reader
│   ├── read_transmission_delay.py     # Estimation based on packet size
│   ├── read_link_capacity.py          # Dispersion register reader (delta_t)
│   ├── run_throughput_test.py         # iperf throughput automation
│   ├── send_probes.py                 # Scapy probe trigger
│   └── test_link_capacity.py          # Packet-pair automation
├── build/main.json                    # Compiled artifact for BMv2

## Running the Complete Ecosystem

You need **2 terminals** open in the container simultaneously.

**Step-by-step:**
1. Start the topology and program the switch:
   ```bash
   sudo python3 topologies/linear_topo.py --json build/main.json
   bash ./control_plane/program_linear.sh
   ```
2. Generate traffic (in Mininet CLI):
   ```bash
   mininet> h1 ping -c 5 10.0.0.2
   ```

### Terminal 2 — Read Metrics

With the traffic running, use a separate terminal to invoke the Python readers via the Thrift protocol:

```bash
# Read Latency
python3 control_plane/read_latency.py --thrift-port 9090 --indices 2

# Read Throughput (will run indefinitely updating per second)
python3 control_plane/read_throughput.py --thrift-port 9090 --indices 2

# Read Transmission Delay (assuming link configured at 10 Mbps)
python3 control_plane/read_transmission_delay.py --thrift-port 9090 --indices 2 --link-bw-mbps 10
```

## Supported Metrics

Below we explain how to test each of the 4 supported network parameters, detailing the command to execute and the mechanics behind the measurement.

### 1. Latency
**How it works:** 
The source switch clones data packets to create a telemetry probe, inserting its send timestamp ($t_{send}$). The destination switch (reflector) receives the probe, marks its internal processing time ($t_{proc}$), and returns it. The source receives it back, gets the current time ($t_{recv}$), and calculates the exact round-trip via hardware: `(t_recv - t_send - t_proc) / 2`.
The result is stored in the switch's register and read via Thrift.

### 2. Throughput
**How it works:**
The P4 switch has hardware counters that sum the size of every packet exiting a port. The control plane script polls this counter via Thrift periodically, subtracts the previous value, and calculates bytes/second.

### 3. Transmission Delay
**How it works:**
The P4 hardware stores the size ($L$) of the last forwarded packet in a register. The control plane script reads this register via Thrift and divides it by the physical speed configuration of the link ($R$) set by Mininet: $d_{trans} = L / R$.

### 4. Link Capacity (In-Band Packet-Pair)
**How it works:**
The actual physical link capacity is discovered using two packets in a burst. 
The script generates *only 1 probe packet* and sends it to the **Injector Switch**. The P4 of this switch uses the hardware engine to clone the packet and drop both into the same output queue with maximum priority (Packet-Pair Back-to-Back). 
Upon crossing the network bottleneck, they distance themselves from each other (dispersion). The **Receiver Switch** notes the time Packet 1 arrived ($t_1$). When Packet 2 arrives, it calculates $\Delta T = t_2 - t_1$ using the P4 ALUs, saving the result of $\Delta T$ in a register. The control plane simply reads $\Delta T$ via Thrift and finalizes the calculation: $C = L_{bits} / \Delta T$.

**Step-by-step:**
With the topology (linear or triangle) running and configured in one terminal, simply execute the capacity test in another:
```bash
python3 control_plane/test_link_capacity.py --host h1 --thrift-port 9091 --frame-size 1500
```

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
PROBE_INTERVAL_US=500000 bash ./control_plane/program_triangle.sh
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
