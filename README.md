# ns8-adguard-home

NethServer 8 module for [AdGuard Home](https://github.com/AdguardTeam/AdGuardHome),
a network-wide DNS server that blocks ads and trackers.

The module runs the official AdGuard Home image
(`docker.io/adguard/adguardhome`, currently `v0.107.79`, pinned by digest)
as a rootless container and adds:

- a Traefik route for the AdGuard Home web interface and the
  DNS-over-HTTPS endpoint `https://<host>/dns-query`, with optional Let's
  Encrypt certificate;
- plain DNS on port 53 (TCP and UDP) on the node addresses you choose, with
  the port opened in the node firewall;
- the AdGuard Home user `admin` with a generated password, shown on the
  **Settings** page and changeable there; the setup wizard is never exposed;
- NS8 backup and restore of the AdGuard Home configuration (filters, user
  rules, upstreams, clients, rewrites, access lists).

One instance per node, because it binds port 53 on the host.

## Install

Install a fixed version, so that the Software Center offers later updates:

```
add-module ghcr.io/platypuschan/adguard-home:0.1.0 1
```

The output of the command returns the instance name, for example
`adguard-home1`.

## Configure

Open the module in cluster-admin and set the host name on the **Settings**
page. The web interface is then at `https://<host>/`; the Settings page
links to it and shows the admin user and password and the DNS-over-HTTPS
URL.

The same configuration from the command line:

```
api-cli run module/adguard-home1/configure-module --data '{"host": "adguard.example.org", "http2https": true, "lets_encrypt": true}'
api-cli run module/adguard-home1/get-configuration
```

Optional fields of `configure-module` (omitted fields keep their value):

- `dns_bind_hosts`: IP addresses of the node where DNS is served on port 53.
  The default `["0.0.0.0"]` listens on all IPv4 and IPv6 addresses and must
  be the only entry. Before saving, the module checks that port 53 is free
  on the new addresses: a Samba domain controller, dnsmasq or
  systemd-resolved on the same node already use it. In that case choose the
  node addresses that are still free.
- `admin_password`: new password for the AdGuard Home user `admin` (at most
  72 bytes); empty keeps the current one.

```
api-cli run module/adguard-home1/configure-module --data '{"host": "adguard.example.org", "http2https": true, "lets_encrypt": true, "dns_bind_hosts": ["192.168.1.10"]}'
```

AdGuard Home is restarted only when the listen addresses, the password or
the web port change.

## Use

Point the DNS server setting of your clients (or of the DHCP server of your
network) to the node address. Everything else is configured in the AdGuard
Home web interface: block lists, custom rules, upstream DNS servers,
per-client settings, DNS rewrites, the query log and statistics.

**Access:** port 53 is open in the node firewall. The initial access list of
AdGuard Home (**Settings > DNS settings > Access settings > Allowed
clients**) contains only loopback, private (RFC 1918, ULA), CGNAT and
link-local networks; other clients get no answer. An open resolver on a
public address gets abused for DNS amplification attacks, so widen this
list only for the clients that need it.

The same list applies to DNS-over-HTTPS: AdGuard Home takes the client
address from Traefik's `X-Forwarded-For` header. To use DNS-over-HTTPS from
outside your networks (for example on phones), allow those clients in the
list and, if the node has a public address, block port 53 at your router or
provider firewall, so only DNS-over-HTTPS is reachable from the internet.

The DHCP server of AdGuard Home is not supported: it needs raw sockets and
port 67, which the rootless container does not get. Use the DHCP server of
your router or the NS8 dnsmasq module, and hand out the node address as DNS
server there.

## How the module runs AdGuard Home

AdGuard Home owns its configuration file `state/conf/AdGuardHome.yaml` and
writes every change made in its web interface there. The module manages
only these keys:

| Key | Value |
| --- | --- |
| `http.address` | `127.0.0.1:<TCP_PORT>`, for Traefik |
| `http.doh.insecure_enabled` | `true`: Traefik terminates TLS for DNS-over-HTTPS |
| `users` (entry `admin`) | bcrypt hash of the admin password |
| `dns.bind_hosts`, `dns.port` | the DNS listen addresses, port 53 |

The first configuration starts from `imageroot/pypkg/AdGuardHome.template.yaml`,
the file the setup wizard of AdGuard Home v0.107.79 writes, with the access
list above. When a managed key changes, `configure-module` stops AdGuard
Home, updates the file and starts it again; other keys stay as AdGuard Home
wrote them. The module settings (admin password, listen addresses) are in
`state/adguard.json`.

The Traefik route removes the `Range` request header. AdGuard Home
v0.107.79 is built with Go 1.26.6, whose file server spends excessive CPU
on a `Range` header with many small ranges (CVE-2026-78667, fixed in Go
1.26.9). The login page and its assets need no login, so without this anyone
who can reach the host name could slow down DNS resolution. The web
interface and DNS-over-HTTPS never need partial responses. `update-module`
re-creates the route, so updated instances get it too.

The container uses the host network, so AdGuard Home sees the real client
addresses; NS8 lets rootless services bind ports from 23 up
(`net.ipv4.ip_unprivileged_port_start`). AdGuard Home runs as root of the
rootless container, which is the module user on the host, with
`--no-check-update` (updates come with new module releases). Logs go to the
journal.

Files:

| Path | Content |
| --- | --- |
| `state/adguard.json` (0600) | module settings and the admin password |
| `state/conf/AdGuardHome.yaml` (0600) | AdGuard Home configuration |
| volume `adguard-work` | `data/` (downloaded filters, query log, statistics, sessions), `userfilters/` |

## Backup and restore

Restic saves `state/adguard.json`, `state/conf/AdGuardHome.yaml` and the
`userfilters/` directory. Downloaded filter lists are fetched again after a
restore; the query log and the statistics are not backed up. If the DNS
listen addresses do not exist on the node of a restore or clone, the module
falls back to `0.0.0.0`.

## Uninstall

```
remove-module --no-preserve adguard-home1
```

## Testing

Unit tests (need PyYAML, as in the NS8 agent environment):

```
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

The QEMU tests in `tests/adguard.robot` install the module on Rocky Linux 9
and Debian 13 (`install` scenario) and update it from the last published
release (`update` scenario). They check the Traefik route, admin login, DNS
over UDP, TCP and HTTPS, filtering, the firewall, password and listen
address changes, the busy-port check and the module UI. They run in GitHub
Actions (`Publish images`); to run them by hand:

```
./test-module-install.sh <NODE_ADDR> ghcr.io/platypuschan/adguard-home:latest
./test-module-update.sh <NODE_ADDR> ghcr.io/platypuschan/adguard-home:latest
```

## Release

`CATALOG_VERSION` is the version published to the module catalog. Raise it
in every change that alters the module image (`imageroot`, `ui`,
`build-images.sh`); the Validate workflow checks this. After a merge to
`main`, `Publish images` builds and tests the image, and
`Publish tested catalog version` tags the tested image with that version.

When updating AdGuard Home, update the digest in `build-images.sh` and
compare `imageroot/pypkg/AdGuardHome.template.yaml` with the file the setup
wizard of the new release writes. Existing installations keep their file;
AdGuard Home migrates it to a newer schema itself.

## Dependency updates (Renovate)

The existing `renovate/configure` onboarding PR prepares automatic **proposals**;
regular updates start only after a maintainer reviews and merges it and the
installed Renovate app runs again. Automerge is disabled. Major updates require
Dependency Dashboard approval before normal PR creation; vulnerability alerts
may bypass Renovate's normal approval/rate limits but still require manual merge.
At most two regular update PRs are open, with two created per hour.

Renovate is the only dependency updater configured here:

| Input | Owner / policy |
| --- | --- |
| AdGuard image tag and digest in `build-images.sh` | Shell regex manager, Docker datasource; retain digest pinning |
| Node in `build-images.sh`, `ui/Containerfile`, setup-node | Shell, Dockerfile and Actions managers, one Node.js toolchain group; stay on tested Node 24 (Corepack required) |
| `ui/package.json`, `ui/yarn.lock`, Yarn `packageManager` | npm manager; non-major UI updates grouped, weekly lockfile maintenance |
| Actions, reusable workflows, runner images and policy-test Renovate image | GitHub Actions manager |
| Robot browser runner in `test-module.sh` | Shell regex manager, Docker datasource |
| SSHLibrary in `test-module.sh`, PyYAML in `validate.yml` | Python-pin regex manager, PyPI datasource; PyYAML is a test pin, not an NS8 host update |

NS8 agent/system dependencies and packages inside the upstream AdGuard image
remain owned by NS8/upstream, not by a second package-refresh bot in this repo.
The minimum-core compatibility declaration is manually reviewed, not an updater
input. README version examples and template provenance are documentation, not
runtime pins; review them with each AdGuard proposal. In particular, compare the
setup-wizard template and retain the Range-header mitigation until the new
runtime's Go version/fix is verified.

Image-affecting updates under `ui/**`, `imageroot/**` or `build-images.sh`
use native Renovate `bumpVersions` to raise `CATALOG_VERSION` by one patch,
including lockfile-only refreshes and grouped changes. Test/workflow-only updates
do not raise it. Proposals rebase when behind main; the existing catalog-version
check remains the release gate against parallel proposals reusing a version.
This onboarding changes neither the module version nor dependency versions.

Before merging a dependency PR, review its diff, UI lint/build, catalog version,
and QEMU install/update tests on Rocky 9 and Debian 13. Main-branch build and
tested-version promotion remain responsible for publication; Renovate itself
neither publishes a release nor deploys an installed module. The main branch is
currently unprotected: manual merge gates are policy, not enforced branch rules.

`Renovate policy` CI uses official Renovate 44.222.5 pinned by image digest for
strict validation, native RE2 extraction, resolved package-rule tests and actual
release-bump behavior (manifest, lockfile, mixed group, digest and no-op cases).
Local reproduction:

```sh
image=ghcr.io/renovatebot/renovate:44.222.5@sha256:8a4c49ef19bb71bedf4eaa4d1087a31a1793bd53de41478753d2d648e53eed19
podman run --rm --user=0 -v "$PWD:/work:ro" -w /work --entrypoint renovate-config-validator "$image" --strict renovate.json
podman run --rm --user=0 -v "$PWD:/work:ro" -w /work --entrypoint node "$image" .github/scripts/test-renovate.mjs
podman run --rm --user=0 -v "$PWD:/work:ro" -w /work --entrypoint renovate "$image" --platform=local --dry-run=extract --require-config=required --onboarding=false
```

Extraction runs without credentials or registry lookups; the GitHub-token warning
for Actions dependencies is expected locally, not evidence of successful update
lookups. The hosted app supplies its own authentication after activation.

## Credits

AdGuard Home is developed by AdGuard Software Ltd. under the GPL-3.0.
This module is not affiliated with AdGuard.

## Minimum NS8 core version

This module requires NS8 core **3.23.0** or newer. This conservative minimum
matches the core version recorded by the existing successful QEMU installation
[tests](https://github.com/Platypuschan/ns8-adguard-home/actions/runs/38154896956);
compatibility with older cores has not been verified. The module image
declares this requirement in `org.nethserver.min-core`.
