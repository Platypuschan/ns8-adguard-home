#
# SPDX-License-Identifier: GPL-3.0-or-later
#

"""Traefik route of the AdGuard Home web interface and DoH endpoint."""

import os
import sys

# Traefik removes these request headers before they reach AdGuard Home.
# Range: AdGuard Home v0.107.79 is built with Go 1.26.6, whose
# http.FileServer spends excessive CPU on a Range header with many small
# ranges (CVE-2026-78667, GO-2026-6609, fixed in Go 1.26.9). The login page
# and /assets/* are served without authentication, so anyone who can reach
# the host could slow down DNS resolution. The web interface and DoH never
# need partial responses.
REMOVED_REQUEST_HEADERS = ("Range",)


def route_request(module_id, web_port, host, http2https, lets_encrypt):
    return {
        "instance": module_id,
        "url": f"http://127.0.0.1:{web_port}",
        "host": host,
        "http2https": http2https,
        "lets_encrypt": lets_encrypt,
        "headers": {"request": {name: "" for name in REMOVED_REQUEST_HEADERS}},
    }


def set_route(host, http2https, lets_encrypt):
    """Create or replace the route on the default Traefik of this node."""
    # Only in the NS8 agent environment, not in the unit tests.
    import agent
    import agent.tasks

    traefik_id = agent.resolve_agent_id("traefik@node")
    if traefik_id is None:
        print("Default Traefik instance of this node not found", file=sys.stderr)
        sys.exit(2)
    response = agent.tasks.run(
        agent_id=traefik_id,
        action="set-route",
        data=route_request(os.environ["MODULE_ID"], os.environ["TCP_PORT"], host, http2https, lets_encrypt),
    )
    agent.assert_exp(response["exit_code"] == 0, "Traefik set-route failed")
