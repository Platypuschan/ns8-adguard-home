# SPDX-License-Identifier: GPL-3.0-or-later

import os
import re
import unittest

UNIT = os.path.join(os.path.dirname(__file__), "..", "imageroot", "systemd", "user", "adguard.service")


class WorkDirectoryTest(unittest.TestCase):
    """AdGuard Home refuses to treat a work directory that is not 0700 as
    private (permcheck warning); a new Podman volume is created with 0755."""

    def setUp(self):
        with open(UNIT, encoding="utf-8") as handle:
            self.lines = handle.read().splitlines()

    def test_volume_is_created_and_made_private_before_the_start(self):
        pre = [i for i, line in enumerate(self.lines) if line.startswith("ExecStartPre=")]
        start = next(i for i, line in enumerate(self.lines) if line.startswith("ExecStart="))
        create = next(i for i in pre if "podman volume create --ignore adguard-work" in self.lines[i])
        chmod = next(i for i in pre if "podman unshare chmod 0700" in self.lines[i])
        self.assertLess(create, chmod)
        self.assertLess(chmod, start)

    def test_mode_is_set_inside_the_user_namespace(self):
        line = next(l for l in self.lines if "chmod 0700" in l)
        self.assertIn("podman unshare chmod 0700", line)
        # systemd would expand a single dollar sign.
        self.assertTrue(re.search(r"\$\$\(", line))
        self.assertIn("adguard-work", line)


if __name__ == "__main__":
    unittest.main()
