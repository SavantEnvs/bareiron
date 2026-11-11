#!/usr/bin/env python3
"""Regenerates the starter seeds: python3 mayhem/gen_seeds.py (writes mayhem/<target>/testsuite/*).

A seed is the byte stream one Minecraft 1.21.8 client (protocol 772) sends to the server."""
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def varint(n):
    out = bytearray()
    n &= 0xFFFFFFFF
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def string(s):
    b = s.encode()
    return varint(len(b)) + b


def packet(pid, body=b""):
    inner = varint(pid) + body
    return varint(len(inner)) + inner


def block_pos(x, y, z):
    return struct.pack(">Q", ((x & 0x3FFFFFF) << 38) | ((z & 0x3FFFFFF) << 12) | (y & 0xFFF))


UUID = bytes(range(0xA0, 0xB0))

handshake = lambda nxt: packet(0x00, varint(772) + string("localhost") + struct.pack(">H", 25565) + varint(nxt))
login_start = packet(0x00, string("fuzz") + UUID)
login_ack = packet(0x03)
client_info = packet(0x00, string("en_US") + b"\x0a" + varint(0) + b"\x01\x7f" + varint(1) + b"\x00\x01\x00")
plugin_msg = packet(0x02, string("minecraft:brand") + string("vanilla"))
known_packs = packet(0x07, varint(0))
finish_config = packet(0x03)

JOIN = (handshake(2) + login_start + login_ack + client_info + known_packs + finish_config)
STATUS = handshake(1) + packet(0x00) + packet(0x01, struct.pack(">q", 1234567890))

dbl = lambda v: struct.pack(">d", v)
flt = lambda v: struct.pack(">f", v)

play = {
    "loaded": packet(0x2B),
    "position": packet(0x1D, dbl(8.5) + dbl(70.0) + dbl(8.5) + b"\x01"),
    "position_rotation": packet(0x1E, dbl(-20.25) + dbl(64.0) + dbl(33.75) + flt(90.0) + flt(-15.0) + b"\x00"),
    "rotation": packet(0x1F, flt(180.0) + flt(45.0) + b"\x01"),
    "flags": packet(0x20, b"\x01"),
    "chat": packet(0x08, string("hello world") + struct.pack(">q", 0) + struct.pack(">q", 0) + b"\x00" + varint(0) + b"\x00" * 4),
    "chat_command": packet(0x08, string("!msg fuzz hi") + struct.pack(">q", 0) + struct.pack(">q", 0) + b"\x00" + varint(0) + b"\x00" * 4),
    "client_status": packet(0x0B, b"\x00"),
    "click_container": packet(0x11, varint(0) + varint(0) + struct.pack(">h", 36) + b"\x00" + varint(0) + varint(0)),
    "click_outside": packet(0x11, varint(0) + varint(0) + struct.pack(">h", -999) + b"\x00" + varint(0) + varint(0)),
    "close_container": packet(0x12, varint(0)),
    "held_item": packet(0x34, struct.pack(">H", 3)),
    "swing_arm": packet(0x3C, varint(0)),
    "dig_start": packet(0x28, b"\x00" + block_pos(8, 60, 8) + b"\x01" + varint(1)),
    "dig_finish": packet(0x28, b"\x02" + block_pos(8, 60, 8) + b"\x01" + varint(2)),
    "use_item_on": packet(0x3F, b"\x00" + block_pos(8, 60, 8) + b"\x01" + b"\x00" * 12 + b"\x00\x00" + varint(3)),
    "use_item": packet(0x40, b"\x00" + varint(4) + flt(0.0) + flt(0.0)),
    "attack": packet(0x19, varint(2) + b"\x01" + b"\x00"),
    "interact": packet(0x19, varint(2) + b"\x00" + b"\x00" + b"\x00"),
    "input": packet(0x2A, b"\x20"),
    "command_sprint": packet(0x29, varint(1) + b"\x01" + varint(0)),
    "keep_alive": packet(0x1B, struct.pack(">q", 7)),
}

SESSION_SEEDS = {"status": STATUS, "join": JOIN, "join_plugin": JOIN + plugin_msg}
sequence = [
    ["loaded", "position", "position_rotation", "rotation", "flags"],
    ["chat", "chat_command", "client_status"],
    ["held_item", "dig_start", "dig_finish", "use_item_on", "use_item", "swing_arm"],
    ["click_container", "click_outside", "close_container", "attack", "interact", "input", "command_sprint", "keep_alive"],
]
PLAY_SEEDS = {name: p for name, p in play.items()}
for i, group in enumerate(sequence):
    PLAY_SEEDS["flow_%d" % i] = b"".join(play[n] for n in group)
    SESSION_SEEDS["join_flow_%d" % i] = JOIN + b"".join(play[n] for n in group)
SESSION_SEEDS["legacy_ping"] = b"\xfe\x01\x7a"


def write(target, seeds):
    d = os.path.join(HERE, target, "testsuite")
    os.makedirs(d, exist_ok=True)
    for name, data in seeds.items():
        with open(os.path.join(d, name), "wb") as f:
            f.write(data)


write("fuzz_session", SESSION_SEEDS)
write("fuzz_play", PLAY_SEEDS)
print("wrote %d + %d seeds" % (len(SESSION_SEEDS), len(PLAY_SEEDS)), file=sys.stderr)
