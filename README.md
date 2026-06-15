# In-Band Telemetry & Dynamic Discovery (Digital Twin)

This project implements a **Software-Defined Networking (SDN)** ecosystem using **P4/BMv2** and **Mininet**. It supports in-band active telemetry (latency, throughput, transmission delay, packet-pair for capacity) and an innovative mechanism for **Dynamic Topology Discovery** to generate a real-time **Digital Twin** of the network.

The core differentiator of this project is its **Modular Architecture (Piggybacking)**. The telemetry system acts as an "Active Observer", injecting its rules dynamically into a running commercial network without modifying the underlying infrastructure's routing intelligence.

All route discovery logic and loop mitigation are performed directly in the **Data Plane** by the P4 hardware/simulator, without relying on constant control packets sent to the CPU.

## Software Overview

The repository is strictly divided into two parts to prove its modularity:

1. **`network_simulation/` (Base Infrastructure Simulation):**
   Represents the client/provider network. The Bash scripts in this folder (e.g., `program_complex.sh`) only turn on the switches, assign a factory Datapath ID to them, and install traditional IP routing (IPv4). The network knows nothing about telemetry.

2. **`telemetry_system/` (Your Telemetry Software):**
   Contains the Python intelligence. Your software scans the active network, installs Multicast rules "on top" of the existing configurations (`deploy_telemetry.py`), ejects Discovery Probes, and extracts latency metrics and topology from the BMv2 hardware using the Thrift API (`sdn_controller.py`).

---

## Dynamic Discovery Architecture (The Digital Twin)

The topology discovery mechanism works through a process called **Stateful BFS Flooding**, operating purely in the Data Plane:

1. **Probe Injection:** The controller forges a single packet (Discovery Probe) with `EtherType 0x8899` and injects it into a root switch.
2. **Flooding:** When the P4 Switch receives the probe, it inserts its own ID into the packet and clones/replicates (Multicast) this packet to all its other active ports.
3. **Bidirectional Learning:** When the neighboring switch receives the probe, it reads the sender switch ID from the packet and saves it in its `neighbor_id_reg` (Neighbor Register) exactly at the index corresponding to the ingress port.
4. **Stateful Loop Breaking:** Complex mesh networks with flooding can generate infinite packet storms (Broadcast Storms). To resolve this, the P4 Switch checks its register to see if it **already knew** the sender of that probe. If it did, it drops the probe immediately. This allows the probe to do exactly 1 "ping-pong", safely mapping out loops without causing network crashes.
5. **Digital Twin Generation:** After the flooding settles, the SDN Controller performs a crawl by accessing the management ports. It scans the neighbor tables recursively and compiles all discovered links into a CSV file (`network_state.csv`), representing the exact state of the network at that given moment.

---

## Step-by-Step: Running the Complex Network (5 Switches)

To validate the modular architecture and resilience against routing Loops, follow the step-by-step guide using the Complex Mesh Topology.

### 1. Bring up the Base Infrastructure (Network Engineer)
Open a terminal inside Docker (Terminal 1) and start the physical Mininet simulation:
```bash
sudo python3 topologies/complex_topo.py --json build/main.json
```
*(The topology will come up with 5 switches and multiple loops between them, wait for the `Complex Topology started` message)*

In another Docker terminal (Terminal 2), install the IPv4 routes and hardware IDs:
```bash
bash network_simulation/program_complex.sh
```
> **Note:** The network is now capable of routing conventional pings, but is blind to telemetry.

### 2. Deploy Telemetry (Your Software)
Still in Terminal 2, activate the "Observer" mode of your software. It will dynamically inject mirroring groups based on the detected active ports:
```bash
python3 telemetry_system/deploy_telemetry.py
```
*(Expected output: "Telemetry Multicast successfully deployed to 5 switches".)*

### 3. Dispatch the Discovery Probe (Terminal 1)
At the Mininet prompt (`mininet>`), ask Host 1 to unleash the Flooding Probe into the network:
```bash
mininet> h1 python3 telemetry_system/send_discovery.py --iface h1-eth0
```
> The P4 Data Plane will handle all the complex topology Loop mitigation behind the scenes in microseconds.

### 4. Extract the Digital Twin (Terminal 2)
Make your controller collect the complete hardware view and build the CSV:
```bash
python3 telemetry_system/sdn_controller.py
```

**Expected Result:**
The controller will perfectly map out the entire labyrinth of switches!
```text
[INFO] Starting Topology Discovery & Digital Twin Export...
[INFO] Connecting to Switch 1 (Thrift: 9090)
  -> Found Link: S1 (Port 2) ---> S2
  -> Found Link: S1 (Port 3) ---> S3
[INFO] Connecting to Switch 2 (Thrift: 9091)
  -> Found Link: S2 (Port 1) ---> S1
  -> Found Link: S2 (Port 2) ---> S4
...
[OK] Digital Twin exported to network_state.csv
```

---

## Other Telemetry Metrics

Traditional metrics (Latency, Throughput, and Delay) remain 100% supported and isolated in the telemetry module.
```bash
python3 telemetry_system/read_latency.py --thrift-port 9090 --indices 2
python3 telemetry_system/read_throughput.py --thrift-port 9090 --indices 2
```
