#!/usr/bin/env python3
import argparse
import logging
from dataclasses import dataclass

from scapy.all import ByteField, Ether, Packet, Raw, ShortField, bind_layers, sendp


ETHERTYPE_PROBE = 0x9999
DEFAULT_FRAME_SIZE = 1500
DEFAULT_DST_MAC = "00:00:00:00:0A:02"
DEFAULT_SRC_MAC = "00:00:00:00:0A:01"


class CapacityProbe(Packet):
    name = "CapacityProbe"
    fields_desc = [
        ShortField("probe_id", 1),
        ByteField("pkt_type", 1),
    ]


bind_layers(Ether, CapacityProbe, type=ETHERTYPE_PROBE)


@dataclass(frozen=True)
class ProbeConfig:
    iface: str
    src_mac: str
    dst_mac: str
    frame_size: int
    probe_id: int


def build_probe_frame(src_mac: str, dst_mac: str, frame_size: int, probe_id: int) -> Ether:
    base = Ether(src=src_mac, dst=dst_mac, type=ETHERTYPE_PROBE) / CapacityProbe(probe_id=probe_id, pkt_type=1)
    current_len = len(bytes(base))
    if frame_size < current_len:
        raise ValueError(f"frame_size={frame_size} is smaller than header size={current_len}")

    padding_len = frame_size - current_len
    payload = Raw(b"\x00" * padding_len)
    return base / payload


def parse_args() -> ProbeConfig:
    parser = argparse.ArgumentParser(description="Send single In-Band Capacity Probe trigger")
    parser.add_argument("--iface", required=True, help="Output interface, for example h1-eth0")
    parser.add_argument("--src-mac", default=DEFAULT_SRC_MAC, help="Source MAC address")
    parser.add_argument("--dst-mac", default=DEFAULT_DST_MAC, help="Destination MAC address")
    parser.add_argument("--frame-size", type=int, default=DEFAULT_FRAME_SIZE, help="Target frame size in bytes")
    parser.add_argument("--probe-id", type=lambda x: int(x, 0), default=1, help="Probe ID (hex or int)")
    args = parser.parse_args()
    return ProbeConfig(args.iface, args.src_mac, args.dst_mac, args.frame_size, args.probe_id)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    cfg = parse_args()

    probe_frame = build_probe_frame(cfg.src_mac, cfg.dst_mac, cfg.frame_size, cfg.probe_id)

    logging.info("interface=%s src=%s dst=%s frame_size=%d bytes", cfg.iface, cfg.src_mac, cfg.dst_mac, cfg.frame_size)
    logging.info("ether_type=0x%04x frame_len=%d bytes", ETHERTYPE_PROBE, len(bytes(probe_frame)))
    logging.info("sending ONE In-Band Capacity Probe trigger")
    sendp(probe_frame, iface=cfg.iface, verbose=False)
    logging.info("probe trigger sent")


if __name__ == "__main__":
    main()
