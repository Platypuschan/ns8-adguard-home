# SPDX-License-Identifier: GPL-3.0-or-later

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "imageroot", "pypkg"))
import adguard_route  # noqa: E402


class RouteTest(unittest.TestCase):
    def test_route_removes_the_range_header(self):
        request = adguard_route.route_request("adguard-home1", "20001", "dns.example.org", True, False)
        self.assertEqual(request, {
            "instance": "adguard-home1",
            "url": "http://127.0.0.1:20001",
            "host": "dns.example.org",
            "http2https": True,
            "lets_encrypt": False,
            # An empty value makes Traefik remove the request header
            "headers": {"request": {"Range": ""}},
        })


if __name__ == "__main__":
    unittest.main()
