import subprocess
import unittest

from eve_agent.network_tools import LocalNetworkTools


XML = """<?xml version="1.0"?><nmaprun><host><address addr="192.168.2.42" addrtype="ipv4"/><ports>
<port protocol="tcp" portid="6667"><state state="open"/><service name="irc"/></port>
<port protocol="tcp" portid="6668"><state state="closed"/><service name="irc"/></port>
</ports></host><runstats/></nmaprun>"""


class NetworkToolsTest(unittest.TestCase):
    def test_capability_description_is_limited_to_direct_network_evidence(self):
        description = LocalNetworkTools.capability_description()
        self.assertIn("Vollständiger Operations- und Ergebnisvertrag", description)
        self.assertIn("begrenzten TCP-Portscan", description)
        self.assertIn("erreichbaren IP-Adressen", description)
        self.assertIn("offenen TCP-Portnummern", description)
        self.assertIn("nmap zugeordneten Dienstbezeichnungen", description)
        self.assertIn("ausschließlich", description)

    def test_requested_irc_ports_are_scanned(self):
        commands = []
        def runner(command, **kwargs):
            commands.append(command)
            return subprocess.CompletedProcess(command, 0, XML, "")
        tool = LocalNetworkTools({"subnet": "192.168.2.0/24"}, runner)
        answer = tool.execute_operation("scan", {"ports": [6667, 6668]})
        self.assertIn("192.168.2.42", answer)
        self.assertIn("Port 6667", answer)
        self.assertIn("6667,6668", commands[0])

    def test_external_targets_are_rejected(self):
        tool = LocalNetworkTools({"subnet": "192.168.2.0/24"}, lambda *a, **k: None)
        with self.assertRaises(ValueError):
            tool.execute_operation("scan", {"target": "8.8.8.8", "ports": []})

    def test_default_discovery_contains_requested_standard_ports(self):
        commands = []
        def runner(command, **kwargs):
            commands.append(command)
            return subprocess.CompletedProcess(command, 0, XML, "")
        tool = LocalNetworkTools({"subnet": "192.168.2.0/24"}, runner)
        tool.execute_operation("scan", {"ports": []})
        port_arg = commands[0][commands[0].index("-p") + 1]
        self.assertIn("6667", port_arg)
        self.assertIn("6668", port_arg)

    def test_explicit_port_set_is_not_artificially_limited(self):
        commands = []
        def runner(command, **kwargs):
            commands.append(command)
            return subprocess.CompletedProcess(command, 0, XML, "")
        tool = LocalNetworkTools({"subnet": "192.168.2.0/24"}, runner)

        tool.execute_operation("scan", {"ports": list(range(1000, 1025))})

        port_arg = commands[0][commands[0].index("-p") + 1]
        self.assertEqual(25, len(port_arg.split(",")))


if __name__ == "__main__": unittest.main()
