#!/usr/bin/env python3
import argparse
import logging
import time
from dataclasses import dataclass

from scapy.all import BitField, ByteField, Ether, Packet, bind_layers, sniff


ETHERTYPE_PACKET_PAIR = 0x88B5
DEFAULT_TIMEOUT_S = 10.0


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


@dataclass
class CaptureState:
    arrivals: list[float]
    packets: list[Ether]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sniff two packet-pair probes and estimate link capacity")
    parser.add_argument("--iface", required=True, help="Interface to sniff on, for example probe_s2-eth0")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S, help="Sniff timeout in seconds")
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    args = parse_args()
    state = CaptureState(arrivals=[], packets=[])

    def handle_packet(packet: Ether) -> None:
        telemetry = packet.getlayer(TelemetryPair)
        if telemetry is None or telemetry.msg_type != 2:
            return

        arrival_time = time.perf_counter()
        state.arrivals.append(arrival_time)
        state.packets.append(packet)

        packet_number = len(state.arrivals)
        logging.info(
            "captured packet %d arrival=%.9f len=%d bytes src=%s dst=%s",
            packet_number,
            arrival_time,
            len(bytes(packet)),
            packet.src,
            packet.dst,
        )

    logging.info("sniffing on %s for EtherType 0x%04x", args.iface, ETHERTYPE_PACKET_PAIR)
    sniff(
        iface=args.iface,
        filter="ether proto 0x88b5",
        prn=handle_packet,
        store=False,
        count=2,
        timeout=args.timeout,
    )

    if len(state.arrivals) < 2:
        logging.error("captured only %d packet(s); capacity estimate unavailable", len(state.arrivals))
        raise SystemExit(1)

    first_packet = state.packets[0]
    second_packet = state.packets[1]
    delta_t = state.arrivals[1] - state.arrivals[0]
    if delta_t <= 0:
        logging.error("non-positive delta_t=%.12f s", delta_t)
        raise SystemExit(1)

    packet_bits = len(bytes(first_packet)) * 8
    capacity_bps = packet_bits / delta_t

    logging.info("packet1_len=%d bytes packet2_len=%d bytes", len(bytes(first_packet)), len(bytes(second_packet)))
    logging.info("delta_t=%.12f s", delta_t)
    logging.info("capacity=%.3f bps", capacity_bps)
    print(f"delta_t_seconds={delta_t:.12f}")
    print(f"packet_bits={packet_bits}")
    print(f"capacity_bps={capacity_bps:.3f}")


if __name__ == "__main__":
    main()
