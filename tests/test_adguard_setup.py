# SPDX-License-Identifier: GPL-3.0-or-later

import os
import socket
import stat
import sys
import tempfile
import unittest
from unittest import mock

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "imageroot", "pypkg"))
import adguard_setup  # noqa: E402

LOCAL = ["127.0.0.1", "::1", "192.168.1.10", "fd00::10"]


class StateDirTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = self.tmp.name

    def path(self, *parts):
        return os.path.join(self.dir, *parts)

    def mode(self, *parts):
        return stat.S_IMODE(os.stat(self.path(*parts)).st_mode)


class SettingsTest(StateDirTest):
    def test_ensure_settings_creates_password_once(self):
        first = adguard_setup.ensure_settings(self.dir)
        self.assertTrue(first["admin_password"])
        self.assertEqual(first["dns_bind_hosts"], ["0.0.0.0"])
        self.assertEqual(self.mode(adguard_setup.SETTINGS), 0o600)
        second = adguard_setup.ensure_settings(self.dir)
        self.assertEqual(first, second)

    def test_merge_keeps_missing_fields(self):
        settings = {"admin_password": "old", "dns_bind_hosts": ["192.168.1.10"]}
        merged = adguard_setup.merge_request({"host": "a.test"}, settings, LOCAL)
        self.assertEqual(merged, settings)
        self.assertIsNot(merged, settings)

    def test_merge_sets_password_and_hosts(self):
        settings = {"admin_password": "old", "dns_bind_hosts": ["0.0.0.0"]}
        merged = adguard_setup.merge_request(
            {"admin_password": "new", "dns_bind_hosts": [" 192.168.1.10 ", "FD00::10"]}, settings, LOCAL
        )
        self.assertEqual(merged["admin_password"], "new")
        self.assertEqual(merged["dns_bind_hosts"], ["192.168.1.10", "fd00::10"])
        # Empty password keeps the old one
        merged = adguard_setup.merge_request({"admin_password": ""}, settings, LOCAL)
        self.assertEqual(merged["admin_password"], "old")

    def test_merge_rejects_long_password(self):
        with self.assertRaises(adguard_setup.SettingsError) as context:
            adguard_setup.merge_request({"admin_password": "ä" * 37}, {"admin_password": "x", "dns_bind_hosts": ["0.0.0.0"]})
        self.assertEqual(context.exception.error, "password_too_long")

    def test_merge_falls_back_when_addresses_are_missing(self):
        # Restore or clone on another node: the request has no listen addresses
        settings = {"admin_password": "x", "dns_bind_hosts": ["10.9.9.9"]}
        merged = adguard_setup.merge_request({"host": "a.test"}, settings, LOCAL)
        self.assertEqual(merged["dns_bind_hosts"], ["0.0.0.0"])

    def test_bind_host_errors(self):
        cases = [
            ([], "dns_bind_hosts_empty"),
            (["nonsense"], "invalid_ip_address"),
            (["224.0.0.1"], "invalid_ip_address"),
            (["192.168.1.10", "192.168.1.10"], "duplicate_ip_address"),
            (["0.0.0.0", "192.168.1.10"], "unspecified_address_must_be_alone"),
            (["::", "0.0.0.0"], "unspecified_address_must_be_alone"),
            (["10.9.9.9"], "ip_address_not_on_node"),
            (["1.1.1.1"] * 17, "too_many_dns_bind_hosts"),
        ]
        for hosts, error in cases:
            with self.subTest(hosts=hosts):
                with self.assertRaises(adguard_setup.SettingsError) as context:
                    adguard_setup.normalize_bind_hosts(hosts, LOCAL)
                self.assertEqual(context.exception.error, error)

    def test_unspecified_addresses_need_no_local_match(self):
        self.assertEqual(adguard_setup.normalize_bind_hosts(["::"], []), ["::"])
        self.assertEqual(adguard_setup.normalize_bind_hosts(["0.0.0.0"], []), ["0.0.0.0"])


class PasswordTest(unittest.TestCase):
    def test_bcrypt_round_trip(self):
        hashed = adguard_setup.hash_password("correct horse")
        self.assertTrue(hashed.startswith("$2b$10$"))
        self.assertEqual(len(hashed), 60)
        self.assertTrue(adguard_setup.password_matches("correct horse", hashed))
        self.assertFalse(adguard_setup.password_matches("wrong", hashed))
        self.assertNotEqual(hashed, adguard_setup.hash_password("correct horse"))

    def test_matches_rejects_other_formats(self):
        self.assertFalse(adguard_setup.password_matches("x", ""))
        self.assertFalse(adguard_setup.password_matches("x", None))
        self.assertFalse(adguard_setup.password_matches("x", "plain"))


class ConfigTest(StateDirTest):
    settings = {"admin_password": "secret", "dns_bind_hosts": ["0.0.0.0"]}

    def write(self, settings=None, port="20001"):
        config = adguard_setup.prepare_config(settings or self.settings, port, self.dir)
        if config is not None:
            adguard_setup.save_config(config, self.dir)
        return config is not None

    def load(self):
        with open(self.path(adguard_setup.CONFIG), encoding="utf-8") as stream:
            return yaml.load(stream, Loader=adguard_setup.Loader)

    def test_first_config_comes_from_the_template(self):
        self.assertTrue(self.write())
        config = self.load()
        self.assertEqual(config["schema_version"], 34)
        self.assertEqual(config["http"]["address"], "127.0.0.1:20001")
        self.assertTrue(config["http"]["doh"]["insecure_enabled"])
        self.assertEqual(config["dns"]["bind_hosts"], ["0.0.0.0"])
        self.assertEqual(config["dns"]["port"], 53)
        self.assertIn("192.168.0.0/16", config["dns"]["allowed_clients"])
        self.assertNotIn("0.0.0.0/0", config["dns"]["allowed_clients"])
        self.assertTrue(config["dns"]["upstream_dns"])
        self.assertEqual(config["filtering"]["safe_fs_patterns"], ["/opt/adguardhome/work/userfilters/*"])
        [user] = config["users"]
        self.assertEqual(user["name"], "admin")
        self.assertTrue(adguard_setup.password_matches("secret", user["password"]))
        self.assertEqual(self.mode(adguard_setup.CONFIG_DIR), 0o700)
        self.assertEqual(self.mode(adguard_setup.CONFIG), 0o600)
        self.assertTrue(os.path.exists(self.path(adguard_setup.RESTART_FLAG)))

    def test_unchanged_settings_do_not_rewrite(self):
        self.write()
        os.remove(self.path(adguard_setup.RESTART_FLAG))
        before = self.load()["users"][0]["password"]
        self.assertFalse(self.write())
        self.assertFalse(os.path.exists(self.path(adguard_setup.RESTART_FLAG)))
        self.assertEqual(self.load()["users"][0]["password"], before)

    def test_changes_made_in_adguard_are_kept(self):
        self.write()
        config = self.load()
        config["user_rules"] = ["||ads.example^"]
        config["dns"]["upstream_dns"] = ["9.9.9.9"]
        config["users"].append({"name": "viewer", "password": "$2b$10$x"})
        with open(self.path(adguard_setup.CONFIG), "w", encoding="utf-8") as stream:
            yaml.safe_dump(config, stream)
        self.assertTrue(self.write(
            {"admin_password": "new", "dns_bind_hosts": ["192.168.1.10"]}, port="20002"
        ))
        config = self.load()
        self.assertEqual(config["user_rules"], ["||ads.example^"])
        self.assertEqual(config["dns"]["upstream_dns"], ["9.9.9.9"])
        self.assertEqual(config["dns"]["bind_hosts"], ["192.168.1.10"])
        self.assertEqual(config["http"]["address"], "127.0.0.1:20002")
        self.assertEqual([user["name"] for user in config["users"]], ["admin", "viewer"])
        self.assertTrue(adguard_setup.password_matches("new", config["users"][0]["password"]))

    def test_timestamps_stay_strings(self):
        # AdGuard Home writes RFC 3339 times that Go must read back
        self.write()
        path = self.path(adguard_setup.CONFIG)
        with open(path, encoding="utf-8") as stream:
            content = stream.read()
        content = content.replace(
            "protection_disabled_until: null", "protection_disabled_until: 2026-10-11T07:30:00.5+02:00"
        )
        self.assertIn("2026-10-11T07:30:00.5+02:00", content)
        with open(path, "w", encoding="utf-8") as stream:
            stream.write(content)
        self.assertTrue(self.write({"admin_password": "other", "dns_bind_hosts": ["0.0.0.0"]}))
        with open(path, encoding="utf-8") as stream:
            self.assertIn("protection_disabled_until: 2026-10-11T07:30:00.5+02:00\n", stream.read())

    def test_configured_bind_hosts(self):
        self.assertIsNone(adguard_setup.configured_bind_hosts(self.dir))
        self.write()
        self.assertEqual(adguard_setup.configured_bind_hosts(self.dir), ["0.0.0.0"])


class PortTest(unittest.TestCase):
    def test_detects_a_bound_port(self):
        holder = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.addCleanup(holder.close)
        holder.bind(("127.0.0.1", 0))
        port = holder.getsockname()[1]
        self.assertTrue(adguard_setup.port_in_use("127.0.0.1", port))

    def test_free_port(self):
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        self.assertFalse(adguard_setup.port_in_use("127.0.0.1", port))


class ConfigurationTest(unittest.TestCase):
    def test_output(self):
        output = adguard_setup.configuration(
            {"admin_password": "pw", "dns_bind_hosts": ["0.0.0.0"]},
            "dns.example.org", True, False,
            ["127.0.0.1", "192.168.1.10", "fe80::1", "::1", "fd00::10"],
        )
        self.assertEqual(output["url"], "https://dns.example.org/")
        self.assertEqual(output["doh_url"], "https://dns.example.org/dns-query")
        self.assertEqual(output["admin_user"], "admin")
        self.assertEqual(output["node_addresses"], ["192.168.1.10", "fd00::10"])

    def test_output_before_configuration(self):
        output = adguard_setup.configuration({}, "", False, False)
        self.assertEqual(output["url"], "")
        self.assertEqual(output["admin_password"], "")
        self.assertEqual(output["dns_bind_hosts"], ["0.0.0.0"])


class LocalAddressesTest(unittest.TestCase):
    def test_parses_ip_json(self):
        output = '[{"ifname":"lo","addr_info":[{"local":"127.0.0.1"},{"local":"::1"}]},{"ifname":"eth0","addr_info":[{"local":"192.168.1.10"}]},{"ifname":"x"}]'
        with mock.patch("subprocess.run", return_value=mock.Mock(stdout=output)):
            self.assertEqual(adguard_setup.local_addresses(), ["127.0.0.1", "::1", "192.168.1.10"])


if __name__ == "__main__":
    unittest.main()
