#
# SPDX-License-Identifier: GPL-3.0-or-later
#

"""Settings and the managed part of the AdGuard Home configuration.

AdGuard Home owns its configuration file (conf/AdGuardHome.yaml): everything
changed in its web UI (filters, upstreams, clients, rewrites, access lists)
is written there. The module only manages the keys it must control:

- http.address: the web UI listens on 127.0.0.1:${TCP_PORT} for Traefik;
- http.doh.insecure_enabled: Traefik terminates TLS, so DNS-over-HTTPS
  requests reach AdGuard Home over plain HTTP;
- users: the login of the admin user;
- dns.bind_hosts and dns.port: where plain DNS is served.

The first configuration starts from pypkg/AdGuardHome.template.yaml, the file
the AdGuard Home setup wizard writes, so the setup wizard is never exposed.
The module settings (admin password, DNS listen addresses) are kept in
state/adguard.json.
"""

import contextlib
import ctypes
import ctypes.util
import fcntl
import ipaddress
import json
import os
import secrets
import socket
import subprocess

import yaml

SETTINGS = "adguard.json"
CONFIG_DIR = "conf"
CONFIG = os.path.join(CONFIG_DIR, "AdGuardHome.yaml")
TEMPLATE = os.path.join(os.path.dirname(os.path.realpath(__file__)), "AdGuardHome.template.yaml")
# Set when the managed configuration changed and AdGuard Home has not been
# restarted with it yet; configure-module (80start_services) and
# update-module.d clear it. It survives a failed task, so the next run still
# restarts AdGuard Home.
RESTART_FLAG = "adguard-restart-needed"

ADMIN_USER = "admin"
DNS_PORT = 53
DEFAULT_BIND_HOSTS = ["0.0.0.0"]
MAX_BIND_HOSTS = 16


TIMESTAMP_TAG = "tag:yaml.org,2002:timestamp"


def _without_timestamps(base):
    """Return a PyYAML Loader/Dumper class that treats timestamps as strings.

    AdGuard Home writes times like protection_disabled_until in RFC 3339.
    PyYAML would turn them into datetime objects and write them back in a
    format Go's yaml.v3 cannot read into time.Time, so they stay strings.
    """
    resolvers = {
        first: [item for item in items if item[0] != TIMESTAMP_TAG]
        for first, items in base.yaml_implicit_resolvers.items()
    }
    return type("NoTimestamp" + base.__name__, (base,), {"yaml_implicit_resolvers": resolvers})


Loader = _without_timestamps(yaml.SafeLoader)
Dumper = _without_timestamps(yaml.SafeDumper)


class SettingsError(Exception):
    def __init__(self, field, value, error):
        super().__init__(f"{field}: {error}")
        self.field = field
        self.value = value
        self.error = error


def new_secret():
    # URL-safe characters only, so the password can be typed and pasted
    # without quoting.
    return secrets.token_urlsafe(18)


def _write_private(path, content):
    """Atomically write a file readable by the module user only."""
    temporary = path + ".tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(content)
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def write_private_json(path, data):
    _write_private(path, json.dumps(data, indent=2) + "\n")


@contextlib.contextmanager
def settings_lock(state_dir="."):
    """Serialize settings changes between concurrent tasks."""
    path = os.path.join(state_dir, SETTINGS + ".lock")
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def read_settings(state_dir="."):
    try:
        with open(os.path.join(state_dir, SETTINGS), "r", encoding="utf-8") as stream:
            return json.load(stream)
    except FileNotFoundError:
        return {}


def ensure_settings(state_dir="."):
    """Return the settings; create the admin password once and keep it, also
    across restores and updates."""
    settings = read_settings(state_dir)
    changed = False
    if not settings.get("admin_password"):
        settings["admin_password"] = new_secret()
        changed = True
    if not isinstance(settings.get("dns_bind_hosts"), list) or not settings["dns_bind_hosts"]:
        settings["dns_bind_hosts"] = list(DEFAULT_BIND_HOSTS)
        changed = True
    path = os.path.join(state_dir, SETTINGS)
    if changed:
        write_private_json(path, settings)
    else:
        os.chmod(path, 0o600)
    return settings


def local_addresses():
    """Return the IP addresses configured on this node."""
    output = subprocess.run(
        ["ip", "-j", "address", "show"], check=True, capture_output=True, text=True
    ).stdout
    addresses = []
    for interface in json.loads(output):
        for item in interface.get("addr_info", []):
            if item.get("local"):
                addresses.append(str(ipaddress.ip_address(item["local"])))
    return addresses


def normalize_bind_hosts(hosts, local=None):
    """Validate the DNS listen addresses of a configure-module request.

    An unspecified address (0.0.0.0 or ::) listens on every address of the
    node, IPv4 and IPv6, and cannot be combined with other addresses: the
    second socket would fail with "address already in use". Other addresses
    must be configured on the node, or AdGuard Home does not start.
    """
    field = "dns_bind_hosts"
    if not hosts:
        raise SettingsError(field, "", "dns_bind_hosts_empty")
    if len(hosts) > MAX_BIND_HOSTS:
        raise SettingsError(field, ",".join(hosts), "too_many_dns_bind_hosts")
    result = []
    for index, value in enumerate(hosts):
        text = (value or "").strip()
        try:
            address = ipaddress.ip_address(text)
        except ValueError:
            raise SettingsError(f"{field}.{index}", text, "invalid_ip_address") from None
        if address.is_multicast:
            raise SettingsError(f"{field}.{index}", text, "invalid_ip_address")
        normalized = str(address)
        if normalized in result:
            raise SettingsError(f"{field}.{index}", text, "duplicate_ip_address")
        result.append(normalized)
    if len(result) > 1 and any(ipaddress.ip_address(item).is_unspecified for item in result):
        raise SettingsError(field, ",".join(result), "unspecified_address_must_be_alone")
    if local is not None:
        for index, item in enumerate(result):
            if not ipaddress.ip_address(item).is_unspecified and item not in local:
                raise SettingsError(f"{field}.{index}", item, "ip_address_not_on_node")
    return result


def _ipv6_enabled():
    try:
        sock = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
    except OSError:
        return False
    sock.close()
    return True


def port_in_use(host, port=DNS_PORT):
    """Return True if TCP or UDP port 53 on host cannot be bound now.

    The module user may bind it: NS8 sets net.ipv4.ip_unprivileged_port_start
    to 23. Another DNS server (Samba DC, dnsmasq, systemd-resolved) holding
    the port makes AdGuard Home fail at start, so it is checked first.
    """
    address = ipaddress.ip_address(host)
    if address.version == 4 and address.is_unspecified and _ipv6_enabled():
        # Go listens on 0.0.0.0 with a dual-stack IPv6 socket, which also
        # conflicts with DNS servers bound to IPv6 addresses only.
        address = ipaddress.ip_address("::")
    family = socket.AF_INET6 if address.version == 6 else socket.AF_INET
    for kind in (socket.SOCK_STREAM, socket.SOCK_DGRAM):
        sock = socket.socket(family, kind)
        try:
            if kind == socket.SOCK_STREAM:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if address.version == 6 and address.is_unspecified:
                sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
            sock.bind((str(address), port))
        except OSError:
            return True
        finally:
            sock.close()
    return False


def merge_request(data, settings, local=None):
    """Return new settings for a configure-module request (nothing is saved).

    Fields missing from the request keep their value: clone and restore send
    the host settings only. On another node the stored listen addresses can
    be missing; then the module falls back to all addresses.
    """
    result = dict(settings)
    if "dns_bind_hosts" in data:
        result["dns_bind_hosts"] = normalize_bind_hosts(data["dns_bind_hosts"], local)
    elif local is not None:
        try:
            normalize_bind_hosts(result["dns_bind_hosts"], local)
        except SettingsError:
            result["dns_bind_hosts"] = list(DEFAULT_BIND_HOSTS)
    password = data.get("admin_password")
    if password:
        # bcrypt (and Go's bcrypt in AdGuard Home) handles 72 bytes at most.
        if len(password.encode("utf-8")) > 72:
            raise SettingsError("admin_password", "", "password_too_long")
        result["admin_password"] = password
    return result


def save_settings(settings, state_dir="."):
    write_private_json(os.path.join(state_dir, SETTINGS), settings)


# bcrypt from libxcrypt (Rocky Linux 9 and Debian 13 both ship it); the agent
# Python environment has no bcrypt module and the crypt module is gone from
# Python 3.13.
def _libcrypt():
    library = ctypes.CDLL(ctypes.util.find_library("crypt") or "libcrypt.so.1", use_errno=True)
    library.crypt_gensalt.restype = ctypes.c_char_p
    library.crypt_gensalt.argtypes = [ctypes.c_char_p, ctypes.c_ulong, ctypes.c_char_p, ctypes.c_int]
    library.crypt.restype = ctypes.c_char_p
    library.crypt.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
    return library


def hash_password(password):
    library = _libcrypt()
    salt = library.crypt_gensalt(b"$2b$", 10, None, 0)
    if not salt:
        raise OSError(ctypes.get_errno(), "crypt_gensalt failed")
    result = library.crypt(password.encode("utf-8"), salt)
    if not result or not result.startswith(b"$2b$"):
        raise OSError(ctypes.get_errno(), "bcrypt hashing failed")
    return result.decode("ascii")


def password_matches(password, hashed):
    if not isinstance(hashed, str) or not hashed.startswith(("$2a$", "$2b$", "$2y$")):
        return False
    result = _libcrypt().crypt(password.encode("utf-8"), hashed.encode("ascii"))
    return bool(result) and secrets.compare_digest(result.decode("ascii"), hashed)


def read_config(state_dir="."):
    """Return the AdGuard Home configuration, or None before the first one."""
    try:
        with open(os.path.join(state_dir, CONFIG), "r", encoding="utf-8") as stream:
            return yaml.load(stream, Loader=Loader) or {}
    except FileNotFoundError:
        return None


def configured_bind_hosts(state_dir="."):
    """Listen addresses AdGuard Home was configured with, or None."""
    config = read_config(state_dir)
    if config is None:
        return None
    return list((config.get("dns") or {}).get("bind_hosts") or [])


def apply_managed(config, settings, web_port, hash_function=hash_password):
    """Set the managed keys in config; return True if anything changed."""
    changed = False

    def put(section, key, value):
        nonlocal changed
        if section.get(key) != value:
            section[key] = value
            changed = True

    def section(parent, key):
        nonlocal changed
        if not isinstance(parent.get(key), dict):
            parent[key] = {}
            changed = True
        return parent[key]

    http = section(config, "http")
    put(http, "address", f"127.0.0.1:{web_port}")
    put(section(http, "doh"), "insecure_enabled", True)

    users = config.get("users")
    if not isinstance(users, list):
        users = []
        config["users"] = users
        changed = True
    admin = next((user for user in users if isinstance(user, dict) and user.get("name") == ADMIN_USER), None)
    if admin is None:
        users.insert(0, {"name": ADMIN_USER, "password": hash_function(settings["admin_password"])})
        changed = True
    elif not password_matches(settings["admin_password"], admin.get("password")):
        admin["password"] = hash_function(settings["admin_password"])
        changed = True

    dns = section(config, "dns")
    put(dns, "bind_hosts", list(settings["dns_bind_hosts"]))
    put(dns, "port", DNS_PORT)
    return changed


def prepare_config(settings, web_port, state_dir="."):
    """Return the configuration with the managed keys applied, or None if
    AdGuardHome.yaml already has them. The first one comes from the
    template."""
    config = read_config(state_dir)
    if config is None:
        with open(TEMPLATE, "r", encoding="utf-8") as stream:
            config = yaml.load(stream, Loader=Loader)
        apply_managed(config, settings, web_port)
        return config
    return config if apply_managed(config, settings, web_port) else None


def save_config(config, state_dir="."):
    """Write AdGuardHome.yaml and set RESTART_FLAG.

    AdGuard Home keeps its configuration in memory and rewrites the whole
    file on every change made in its UI, so stop it before calling this.
    """
    directory = os.path.join(state_dir, CONFIG_DIR)
    os.makedirs(directory, mode=0o700, exist_ok=True)
    os.chmod(directory, 0o700)
    _write_private(
        os.path.join(state_dir, CONFIG),
        yaml.dump(config, Dumper=Dumper, sort_keys=False, default_flow_style=False, allow_unicode=True),
    )
    with open(os.path.join(state_dir, RESTART_FLAG), "w", encoding="utf-8"):
        pass


def ui_url(host):
    return f"https://{host}/" if host else ""


def doh_url(host):
    return f"https://{host}/dns-query" if host else ""


def configuration(settings, host, http2https, lets_encrypt, addresses=()):
    """Output of get-configuration."""
    return {
        "host": host,
        "http2https": http2https,
        "lets_encrypt": lets_encrypt,
        "url": ui_url(host),
        "doh_url": doh_url(host),
        "admin_user": ADMIN_USER,
        "admin_password": settings.get("admin_password", ""),
        "dns_bind_hosts": list(settings.get("dns_bind_hosts") or DEFAULT_BIND_HOSTS),
        # Candidates for the listen addresses shown in the UI.
        "node_addresses": [
            item for item in addresses
            if not ipaddress.ip_address(item).is_loopback and not ipaddress.ip_address(item).is_link_local
        ],
    }
