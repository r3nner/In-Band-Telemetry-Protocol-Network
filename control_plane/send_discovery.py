#!/usr/bin/env python3
import argparse
import logging
from scapy.all import ByteField, Ether, Packet, ShortField, bind_layers, sendp

ETHERTYPE_DISCOVERY = 0x8899
DEFAULT_IFACE = "h1-eth0"

class DiscoveryProbe(Packet):
    name = "DiscoveryProbe"
    fields_desc = [
        ShortField("source_switch_id", 0),
        ShortField("source_port", 0),
        ByteField("ttl", 10),
    ]

bind_layers(Ether, DiscoveryProbe, type=ETHERTYPE_DISCOVERY)

def main():
    parser = argparse.ArgumentParser(description="Send initial Topology Discovery Probe")
    parser.add_argument("--iface", default=DEFAULT_IFACE, help="Interface to inject the probe")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

    # Initial packet has source_switch_id = 0 so the first switch knows it comes from the controller/host
    probe = Ether(src="00:00:00:00:00:00", dst="ff:ff:ff:ff:ff:ff", type=ETHERTYPE_DISCOVERY) / DiscoveryProbe(source_switch_id=0, source_port=0, ttl=10)
    
    logging.info(f"Injecting Discovery Probe into {args.iface} (TTL 10)...")
    sendp(probe, iface=args.iface, verbose=False)
    logging.info("Probe injected.")

if __name__ == "__main__":
    main()
