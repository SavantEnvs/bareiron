#!/usr/bin/env python3
"""Behavioral oracle for bareiron: starts the normal-flag server and speaks Minecraft 1.21.8 to it.

Prints one `PASS <name>` / `FAIL <name>: <why>` line per check; mayhem/test.sh turns them into CTRF."""
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time

SERVER = sys.argv[1]
PORT = 25565
results = []
DEADLINE = time.time() + 120


def check(name, cond, why=""):
    results.append((name, bool(cond), why))
    print(("PASS %s" % name) if cond else ("FAIL %s: %s" % (name, why)), flush=True)


def varint(n):
    out = bytearray()
    n &= 0xFFFFFFFF
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | 0x80 if n else b)
        if not n:
            return bytes(out)


def string(s):
    b = s.encode()
    return varint(len(b)) + b


def packet(pid, body=b""):
    inner = varint(pid) + body
    return varint(len(inner)) + inner


class Client:
    def __init__(self):
        deadline = time.time() + 15
        while True:
            try:
                self.s = socket.create_connection(("127.0.0.1", PORT), timeout=10)
                break
            except OSError:
                if time.time() > deadline:
                    raise
                time.sleep(0.1)
        self.buf = b""

    def need(self, n):
        while len(self.buf) < n:
            if time.time() > DEADLINE:
                raise TimeoutError("oracle deadline exceeded")
            d = self.s.recv(65536)
            if not d:
                raise EOFError("server closed the connection")
            self.buf += d
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def read_varint(self):
        v = shift = 0
        while True:
            b = self.need(1)[0]
            v |= (b & 0x7F) << shift
            if not b & 0x80:
                return v
            shift += 7

    def read_packet(self):
        length = self.read_varint()
        body = self.need(length)
        pid, off = 0, 0
        shift = 0
        while True:
            b = body[off]
            off += 1
            pid |= (b & 0x7F) << shift
            if not b & 0x80:
                break
            shift += 7
        return pid, body[off:]

    def read_until(self, want, limit=4000):
        seen = []
        for _ in range(limit):
            pid, body = self.read_packet()
            if pid == want:
                return body, seen
            seen.append(pid)
        raise RuntimeError("packet 0x%02x never arrived" % want)

    def send(self, data):
        self.s.sendall(data)


def handshake(nxt):
    return packet(0x00, varint(772) + string("localhost") + struct.pack(">H", PORT) + varint(nxt))


def main():
    work = tempfile.mkdtemp(prefix="bareiron-oracle-")
    server = subprocess.Popen([SERVER], cwd=work, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        # --- server list ping -------------------------------------------------------------------
        c = Client()
        c.send(handshake(1) + packet(0x00))
        pid, body = c.read_packet()
        n, off = 0, 0
        while body[off] & 0x80:
            off += 1
        off += 1
        status = json.loads(body[off:].decode())
        check("status: packet id is 0x00", pid == 0x00, "got %#x" % pid)
        check("status: protocol is 772 (1.21.8)", status["version"]["protocol"] == 772, status)
        check("status: motd is 'A bareiron server'", status["description"]["text"] == "A bareiron server", status)
        c.send(packet(0x01, struct.pack(">q", 0x1122334455667788)))
        pid, body = c.read_packet()
        check("ping: pong echoes the payload", pid == 0x01 and struct.unpack(">q", body)[0] == 0x1122334455667788, (pid, body))
        c.s.close()

        # --- login + configuration --------------------------------------------------------------
        uuid = bytes(range(0xB0, 0xC0))
        c = Client()
        c.send(handshake(2) + packet(0x00, string("oracle") + uuid))
        pid, body = c.read_packet()
        check("login: login success is packet 0x02", pid == 0x02, "got %#x" % pid)
        check("login: server echoes the uuid", body[:16] == uuid, body[:16].hex())
        check("login: server echoes the name", body[16:23] == b"\x06oracle", body[16:23])
        c.send(packet(0x03))
        c.send(packet(0x00, string("en_US") + b"\x0a" + varint(0) + b"\x01\x7f" + varint(1) + b"\x00\x01\x00"))
        pid, body = c.read_packet()
        check("config: server sends known packs (0x0E) for minecraft:core 1.21.8",
              pid == 0x0E and b"minecraft" in body and b"1.21.8" in body, (pid, body))
        c.send(packet(0x07, varint(0)))
        body, seen = c.read_until(0x03)
        check("config: registry data (0x07) precedes finish configuration", seen.count(0x07) > 5, seen[:20])

        # --- play ------------------------------------------------------------------------------
        c.send(packet(0x03))
        body, seen = c.read_until(0x41)
        check("play: login (0x2B) is the first play packet", seen[:1] == [0x2B], seen)
        tp, off = 0, 0
        while body[off] & 0x80:
            off += 1
        off += 1
        x, y, z = struct.unpack(">ddd", body[off:off + 24])
        check("play: new player spawns at x=8.5, z=8.5", (x, z) == (8.5, 8.5), (x, z))
        check("play: spawn height is terrain height + 1 (y=67)", y == 67.0, y)
        c.send(packet(0x2B))
        ids = []
        for _ in range(200):
            pid, body = c.read_packet()
            ids.append(pid)
            if ids.count(0x27) >= 3 and 0x26 in ids:
                break
        check("play: server streams chunk data (0x27)", ids.count(0x27) >= 3, ids)
        check("play: server sends the initial inventory and held item", 0x14 in ids and 0x62 in ids, ids)

        c.send(packet(0x08, string("hello oracle") + struct.pack(">qq", 0, 0) + b"\x00" + varint(0) + b"\x00\x00\x00\x00"))
        body, _ = c.read_until(0x72)
        check("chat: message is broadcast as '<oracle> hello oracle'", b"<oracle> hello oracle" in body, body)

        c.send(packet(0x08, string("!help") + struct.pack(">qq", 0, 0) + b"\x00" + varint(0) + b"\x00\x00\x00\x00"))
        body, _ = c.read_until(0x72)
        check("chat: '!help' command replies with the command list", b"!msg <player> <message>" in body, body)

        c.send(packet(0x08, string("!nope") + struct.pack(">qq", 0, 0) + b"\x00" + varint(0) + b"\x00\x00\x00\x00"))
        body, _ = c.read_until(0x72)
        check("chat: unknown '!' command is reported", b"Unknown command" in body, body)

        c.send(packet(0x1D, struct.pack(">ddd", 100.5, 90.0, -40.5) + b"\x00"))
        body, _ = c.read_until(0x57)
        check("move: crossing chunks re-centers the client's chunk view (0x57)", len(body) >= 2, body)
        c.s.close()
    except Exception as e:  # noqa: BLE001
        check("oracle ran to completion", False, "%s: %s" % (type(e).__name__, e))
    finally:
        server.kill()
        server.wait()
        shutil.rmtree(work, ignore_errors=True)
    return 0


main()
