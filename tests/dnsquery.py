#!/usr/bin/env python3

# SPDX-License-Identifier: GPL-3.0-or-later

"""Minimal DNS client for the module tests (the test nodes have no dig).

Usage: dnsquery.py SERVER NAME [udp|tcp|doh-wire]
Prints "rcode=<n> a=<addresses>"; with doh-wire, prints the base64url
DNS-over-HTTPS GET parameter of the query instead.
"""

import base64
import random
import socket
import struct
import sys


def build_query(name, ident):
    header = struct.pack("!HHHHHH", ident, 0x0100, 1, 0, 0, 0)
    labels = b"".join(bytes([len(part)]) + part.encode("ascii") for part in name.rstrip(".").split("."))
    return header + labels + b"\x00" + struct.pack("!HH", 1, 1)


def skip_name(data, offset):
    while True:
        length = data[offset]
        if length == 0:
            return offset + 1
        if length & 0xC0 == 0xC0:
            return offset + 2
        offset += length + 1


def parse_response(data, ident):
    got_ident, flags, qdcount, ancount = struct.unpack("!HHHH", data[:8])
    if got_ident != ident:
        raise ValueError("wrong response id")
    offset = 12
    for _ in range(qdcount):
        offset = skip_name(data, offset) + 4
    addresses = []
    for _ in range(ancount):
        offset = skip_name(data, offset)
        rtype, _class, _ttl, length = struct.unpack("!HHIH", data[offset:offset + 10])
        offset += 10
        if rtype == 1 and length == 4:
            addresses.append(socket.inet_ntoa(data[offset:offset + 4]))
        offset += length
    return flags & 0x000F, addresses


def main():
    server, name = sys.argv[1], sys.argv[2]
    mode = sys.argv[3] if len(sys.argv) > 3 else "udp"
    ident = random.randint(1, 0xFFFF)
    query = build_query(name, ident)
    if mode == "doh-wire":
        print(base64.urlsafe_b64encode(build_query(name, 0)).rstrip(b"=").decode("ascii"))
        return
    family = socket.AF_INET6 if ":" in server else socket.AF_INET
    if mode == "tcp":
        with socket.create_connection((server, 53), timeout=5) as sock:
            sock.sendall(struct.pack("!H", len(query)) + query)
            length = struct.unpack("!H", sock.recv(2))[0]
            data = b""
            while len(data) < length:
                data += sock.recv(length - len(data))
    else:
        with socket.socket(family, socket.SOCK_DGRAM) as sock:
            sock.settimeout(5)
            sock.sendto(query, (server, 53))
            data = sock.recv(4096)
    rcode, addresses = parse_response(data, ident)
    print(f"rcode={rcode} a={','.join(addresses)}")


if __name__ == "__main__":
    main()
