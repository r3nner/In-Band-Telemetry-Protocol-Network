# In-Band Telemetry & Dynamic Discovery (Digital Twin)

This project implements a **Software-Defined Networking (SDN)** ecosystem using **P4/BMv2** and **Mininet**. It supports in-band active telemetry (latency, throughput, transmission delay, packet-pair for capacity) and an innovative mechanism for **Dynamic Topology Discovery** to generate a real-time **Digital Twin** of the network.

All route discovery logic and loop mitigation are performed directly in the **Data Plane** by the P4 hardware/simulator, without relying on constant control packets sent to the CPU.

## Software Overview

The software is divided into two main layers:
1. **Data Plane (P4):** Written in P4_16 (`main.p4`). It is responsible for processing packets line by line. It contains routing tables, multicast control tables (for packet replication), and registers (SRAM memory) that store network state, such as the **Neighbor Table** and time/byte counters.
2. **Control Plane (Python/Thrift):** A set of Python scripts (`control_plane/`) that interact with the P4 switches. They do not process packets directly; instead, they inject rules into tables, dispatch forged packets into the network (using `Scapy`), and asynchronously read the SRAM (registers) of the switch via the Thrift API to extract metrics and generate the network state file (CSV).

---

## Dynamic Discovery Architecture (The Digital Twin)

The topology discovery mechanism works through a process called **Stateful BFS Flooding**, operating purely in the Data Plane:

1. **Probe Injection:** The controller forges a single packet (Discovery Probe) with `EtherType 0x8899` and injects it into a root switch.
2. **Flooding:** When the P4 Switch receives the probe, it inserts its own ID into the packet and clones/replicates (Multicast) this packet to all its other active ports.
3. **Bidirectional Learning:** When the neighboring switch receives the probe, it reads the sender switch ID from the packet and saves it in its `neighbor_id_reg` (Neighbor Register) exactly at the index corresponding to the ingress port.
4. **Stateful Loop Breaking:** Networks with flooding can generate infinite packet storms (Broadcast Storms). To resolve this, before propagating a packet forward, the P4 Switch checks its register to see if it **already knew** the sender of that probe. If it did, it drops the probe immediately. This allows the probe to do exactly 1 "ping-pong" so that both sides of the cable learn who the neighbor is, and the packet storm ceases naturally and extremely quickly.
5. **Digital Twin Generation:** After the flooding settles, the SDN Controller (Python script) performs a crawl by accessing the Thrift Port of the first switch. It reads the neighbor table, finds who is connected, hops to the Thrift IPs of those discovered neighbors, and repeats the process recursively. Finally, it compiles all discovered links into a CSV file (`network_state.csv`), representing the exact state of the network at that given moment.

---

## Step-by-Step: Discovering the Network Topology

To generate the network's Digital Twin at any given moment, open your terminal (with Docker running and files compiled) and follow the steps below. Two interactive terminals inside the container are required.

### 1. Start the Network (Terminal 1)
Bring up the linear topology with BMv2 virtual switches.
```bash
sudo python3 topologies/linear_topo.py --json build/main.json
```
**What happens:** The script uses Mininet to allocate isolated network namespaces, creating hosts (`h1`, `h2`) and switches (`s1`, `s2`) and physically connecting them via virtual ports. The `main.json` file instructs the switch to run our P4 code. Leave this terminal open (you will be in the `mininet>` CLI).

### 2. Initialize SDN Rules (Terminal 2)
In another terminal within the same container, run:
```bash
bash ./control_plane/program_sdn.sh
```
**What happens:** This script uses the `simple_switch_CLI` tool to populate the P4 tables via Thrift. It assigns a unique ID to each Switch (e.g., `s1` = ID 1) by inserting a rule into the `node_info` table. It also creates Multicast groups in the BMv2 replication engine, allowing the discovery probe to be mirrored to all ports.

### 3. Dispatch the Discovery Probe (Terminal 1)
At the Mininet prompt (`mininet>`), inject the discovery packet:
```bash
mininet> h1 python3 control_plane/send_discovery.py --iface h1-eth0
```
**What happens:** Host `h1` uses Python's `Scapy` package to build a raw Ethernet frame with the custom type `0x8899`. Because this command is run "inside" `h1`, the packet physically enters the port of switch `s1`. The P4 intercepts it, recognizes the type, and triggers the Flooding Architecture (explained in the previous section). In milliseconds, the entire network discovers its neighbors bidirectionally and saves them in SRAM.

### 4. Generate the Digital Twin (Terminal 2)
With the network now self-discovered in the switches' memory, run the extractor:
```bash
python3 control_plane/sdn_controller.py
```
**What happens:** The Python script connects to `s1` (Thrift port `9090`), requests to read the `neighbor_id_reg` array. It discovers that on port 2 there is a neighbor with ID 2 (`s2`). It notes the connection, connects to the Thrift of `s2` (`9091`), makes the same read, and cross-references the data. Upon finishing the recursion, it outputs the `network_state.csv` file detailing every link and bidirectional port in your network.

---

## Other Telemetry Metrics

Beyond topology discovery, this ecosystem supports active telemetry. You can run scripts like `read_latency.py`, `read_throughput.py`, `read_transmission_delay.py`, and `test_link_capacity.py` in the control plane to gather real-time performance data directly from the P4 hardware registers.
