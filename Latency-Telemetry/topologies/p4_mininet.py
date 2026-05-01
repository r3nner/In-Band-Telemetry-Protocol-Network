#!/usr/bin/env python3
import os

from mininet.log import info
from mininet.moduledeps import pathCheck
from mininet.node import Host, Switch


class P4Host(Host):
    def config(self, **params):
        result = super().config(**params)

        intf = self.defaultIntf()
        for offload in ("rx", "tx", "sg"):
            self.cmd(f"/sbin/ethtool --offload {intf} {offload} off")

        # IPv6 is disabled to avoid noisy neighbor discovery traffic during tests.
        self.cmd("sysctl -w net.ipv6.conf.all.disable_ipv6=1")
        self.cmd("sysctl -w net.ipv6.conf.default.disable_ipv6=1")
        self.cmd("sysctl -w net.ipv6.conf.lo.disable_ipv6=1")

        return result


class P4Switch(Switch):
    next_device_id = 0

    def __init__(
        self,
        name,
        sw_path="simple_switch",
        json_path=None,
        thrift_port=None,
        pcap_dump=False,
        log_console=False,
        device_id=None,
        **kwargs,
    ):
        Switch.__init__(self, name, **kwargs)

        pathCheck(sw_path)
        if json_path is None:
            raise ValueError("json_path is required for P4Switch")
        if not os.path.isfile(json_path):
            raise FileNotFoundError(f"P4 JSON not found: {json_path}")

        self.sw_path = sw_path
        self.json_path = json_path
        self.thrift_port = thrift_port
        self.pcap_dump = pcap_dump
        self.log_console = log_console

        if device_id is None:
            self.device_id = P4Switch.next_device_id
            P4Switch.next_device_id += 1
        else:
            self.device_id = device_id

    def start(self, controllers):  # pylint: disable=unused-argument
        args = [self.sw_path]

        for intf_name, intf in self.intfs.items():
            if intf_name == "lo":
                continue

            port = self.ports[intf]
            args.extend(["-i", f"{port}@{intf}"])

        if self.thrift_port is not None:
            args.extend(["--thrift-port", str(self.thrift_port)])

        args.extend(["--device-id", str(self.device_id)])

        if self.pcap_dump:
            args.append("--pcap")

        if self.log_console:
            args.append("--log-console")

        args.append(self.json_path)

        log_path = f"/tmp/{self.name}.log"
        pid_path = f"/tmp/{self.name}.pid"

        cmd = " ".join(str(x) for x in args)
        info(f"*** Starting {self.name}: {cmd}\n")
        self.cmd(f"{cmd} > {log_path} 2>&1 & echo $! > {pid_path}")

    def stop(self, deleteIntfs=True):
        pid_path = f"/tmp/{self.name}.pid"
        self.cmd(f"if [ -f {pid_path} ]; then kill -9 $(cat {pid_path}); fi")
        self.cmd(f"rm -f {pid_path}")
        super().stop(deleteIntfs)

    def attach(self, intf):
        info(f"*** Warning: cannot attach to P4Switch {self.name} interface {intf}\n")

    def detach(self, intf):
        info(f"*** Warning: cannot detach from P4Switch {self.name} interface {intf}\n")
