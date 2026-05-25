#!/usr/bin/env python3
import argparse
import logging
from dataclasses import dataclass

from scapy.all import BitField, ByteField, Ether, Packet, Raw, bind_layers, sendp


ETHERTYPE_PACKET_PAIR = 0x88B5
DEFAULT_FRAME_SIZE = 1500
DEFAULT_DST_MAC = "00:00:00:00:0A:02"
DEFAULT_SRC_MAC = "00:00:00:00:0A:01"


class TelemetryPair(Packet):
    name = "TelemetryPair"
    fields_desc = [
        ByteField("msg_type", 2),
        ByteField("probe_index", 0),
        ByteField("report_index", 0),
        ByteField("is_returning", 0),
        BitField("t_send", 0, 48),
        BitField("t_proc", 0, 48),
        BitField("latency_value", 0, 48),
    ]


bind_layers(Ether, TelemetryPair, type=ETHERTYPE_PACKET_PAIR)


@dataclass(frozen=True)
class ProbeConfig:
    iface: str
    src_mac: str
    dst_mac: str
    frame_size: int


def build_probe_frame(src_mac: str, dst_mac: str, frame_size: int) -> Ether:
    base = Ether(src=src_mac, dst=dst_mac, type=ETHERTYPE_PACKET_PAIR) / TelemetryPair()
    current_len = len(bytes(base))
    if frame_size < current_len:
        raise ValueError(f"frame_size={frame_size} is smaller than header size={current_len}")

    padding_len = frame_size - current_len
    payload = Raw(b"\x00" * padding_len)
    return base / payload


def parse_args() -> ProbeConfig:
    parser = argparse.ArgumentParser(description="Send back-to-back packet-pair probes with Scapy")
    parser.add_argument("--iface", required=True, help="Output interface, for example probe_s1-eth0")
    parser.add_argument("--src-mac", default=DEFAULT_SRC_MAC, help="Source MAC address")
    parser.add_argument("--dst-mac", default=DEFAULT_DST_MAC, help="Destination MAC address")
    parser.add_argument("--frame-size", type=int, default=DEFAULT_FRAME_SIZE, help="Target frame size in bytes")
    args = parser.parse_args()
    return ProbeConfig(args.iface, args.src_mac, args.dst_mac, args.frame_size)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    cfg = parse_args()

    probe_frame = build_probe_frame(cfg.src_mac, cfg.dst_mac, cfg.frame_size)
    frames = [probe_frame.copy(), probe_frame.copy()]

    logging.info("interface=%s src=%s dst=%s frame_size=%d bytes", cfg.iface, cfg.src_mac, cfg.dst_mac, cfg.frame_size)
    logging.info("ether_type=0x%04x frame_len=%d bytes", ETHERTYPE_PACKET_PAIR, len(bytes(probe_frame)))
    logging.info("sending two identical probes back-to-back")
    sendp(frames, iface=cfg.iface, inter=0, verbose=False)
    logging.info("probe burst sent")


if __name__ == "__main__":
    main()
