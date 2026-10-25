from __future__ import annotations

import ipaddress
import subprocess
import xml.etree.ElementTree as ET


class LocalNetworkTools:
    """Strict nmap wrapper limited to one configured private LAN."""

    DEFAULT_PORTS = (22, 53, 80, 443, 554, 1883, 6667, 6668, 8008, 8009, 8080, 8123, 8790, 9100)

    def __init__(self, config: dict, runner=None):
        self.network = ipaddress.ip_network(config.get("subnet", "192.168.2.0/24"), strict=True)
        if not self.network.is_private:
            raise ValueError("nmap subnet must be private")
        self.image = config.get("image", "docker.io/instrumentisto/nmap:latest")
        self.timeout = int(config.get("timeout_seconds", 35))
        self.runner = runner or subprocess.run

    @staticmethod
    def capability_description() -> str:
        """Publish the positive information contract of the bounded scanner."""
        return (
            "Vollständiger Operations- und Ergebnisvertrag für den Netzwerk-Read im freigegebenen privaten Heimnetz: "
            "führt einen begrenzten TCP-Portscan aus. Das Ergebnis besteht ausschließlich aus erreichbaren IP-Adressen, "
            "offenen TCP-Portnummern und den von nmap zugeordneten Dienstbezeichnungen."
        )

    @staticmethod
    def minimal_contract() -> dict:
        return {
            "description": "Begrenzter TCP-Portscan ausschließlich im freigegebenen privaten Netz.",
            "operations": {"scan": {"target": "optional IP or subnet", "ports": "optional integer array"}},
        }

    def execute_operation(self, operation: str, arguments: dict) -> str:
        if operation != "scan" or not isinstance(arguments, dict):
            raise ValueError("Nicht veröffentlichte Netzwerkoperation")
        target = str(arguments.get("target") or self.network)
        parsed = ipaddress.ip_network(target, strict=False) if "/" in target else ipaddress.ip_address(target)
        if isinstance(parsed, ipaddress.IPv4Address):
            if parsed not in self.network:
                raise ValueError("EVE darf nur Geräte im konfigurierten Heimnetz scannen.")
        elif not parsed.subnet_of(self.network):
            raise ValueError("EVE darf nur das konfigurierte Heimnetz scannen.")

        raw_ports = arguments.get("ports", [])
        if not isinstance(raw_ports, list) or any(isinstance(port, bool) or not isinstance(port, int) for port in raw_ports):
            raise ValueError("Ports müssen als ganzzahlige Liste angegeben werden")
        ports = sorted(set(raw_ports))
        if any(port < 1 or port > 65535 for port in ports):
            raise ValueError("Ungültige Portnummer")
        command = ["podman", "run", "--rm", "--network", "host", self.image, "--unprivileged", "-sT", "-Pn", "-n", "--open", "--host-timeout", "3s", "-oX", "-"]
        if ports:
            command += ["-p", ",".join(map(str, ports))]
        elif isinstance(parsed, ipaddress.IPv4Address):
            command += ["--top-ports", "100"]
        else:
            command += ["-p", ",".join(map(str, self.DEFAULT_PORTS))]
        command.append(str(parsed))
        result = self.runner(command, capture_output=True, text=True, timeout=self.timeout, check=False)
        xml_start = result.stdout.find("<?xml")
        if xml_start < 0:
            raise RuntimeError("nmap hat kein auswertbares Ergebnis geliefert.")
        root = ET.fromstring(result.stdout[xml_start:])
        found = []
        for host in root.findall("host"):
            address = host.find("address[@addrtype='ipv4']")
            if address is None: continue
            open_ports = []
            for port in host.findall("./ports/port"):
                state = port.find("state")
                if state is not None and state.get("state") == "open":
                    service = port.find("service")
                    open_ports.append((int(port.get("portid")), service.get("name", "unbekannt") if service is not None else "unbekannt"))
            if open_ports: found.append((address.get("addr"), open_ports))
        if not found:
            scope = ", ".join(map(str, ports)) if ports else "den geprüften Ports"
            return f"Ich habe im Ziel {target} keine erreichbaren Geräte mit offenen Ports {scope} gefunden."
        lines = [
            f"{address}: " + ", ".join(
                f"Port {port} ({service})" for port, service in open_ports
            )
            for address, open_ports in found
        ]
        return "Gefunden: " + "; ".join(lines) + "."
