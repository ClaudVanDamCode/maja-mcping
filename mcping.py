#!/usr/bin/env python3
"""mcping: check a Minecraft Java server from the outside, the way a player's client sees it.

Usage:
  python3 mcping.py play.example.com          # port 25565, or the SRV record if there is one
  python3 mcping.py play.example.com:25566
  python3 mcping.py play.example.com --json   # machine-readable output

Python 3.8+, standard library only. One status request per run (the same one the
multiplayer server list sends), so it puts no load on the server.
"""
import argparse
import json
import shutil
import socket
import struct
import subprocess
import sys
import time

DEFAULT_PORT = 25565
PROTOCOL = 767  # any recent value works for a status request


def varint(n):
    out = b""
    while True:
        b = n & 0x7F
        n >>= 7
        out += bytes([b | (0x80 if n else 0)])
        if not n:
            return out


def read_varint(sock):
    n = shift = 0
    for _ in range(5):
        c = sock.recv(1)
        if not c:
            raise IOError("connection closed by server")
        n |= (c[0] & 0x7F) << shift
        shift += 7
        if not c[0] & 0x80:
            return n
    raise IOError("bad varint from server")


def srv_lookup(host):
    """Return (target, port) from _minecraft._tcp.HOST, or None. Uses `dig` when installed."""
    if not shutil.which("dig"):
        return None
    try:
        r = subprocess.run(["dig", "+short", "SRV", "_minecraft._tcp." + host],
                           capture_output=True, text=True, timeout=8)
    except Exception:
        return None
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) == 4 and parts[2].isdigit():
            return parts[3].rstrip("."), int(parts[2])
    return None


def flatten_motd(desc):
    if isinstance(desc, str):
        return desc
    if isinstance(desc, dict):
        text = desc.get("text", "")
        for part in desc.get("extra", []) or []:
            text += flatten_motd(part)
        return text
    if isinstance(desc, list):
        return "".join(flatten_motd(p) for p in desc)
    return ""


def strip_codes(s):
    out, skip = [], False
    for ch in s:
        if skip:
            skip = False
            continue
        if ch == "\u00a7":
            skip = True
            continue
        out.append(ch)
    return "".join(out)


def status(host, port, timeout=6.0):
    t0 = time.time()
    sock = socket.create_connection((host, port), timeout=timeout)
    connect_ms = round((time.time() - t0) * 1000)
    try:
        hs = varint(0) + varint(PROTOCOL) + varint(len(host.encode())) + host.encode() \
            + struct.pack(">H", port) + varint(1)
        sock.sendall(varint(len(hs)) + hs + varint(1) + varint(0))
        read_varint(sock)  # packet length
        read_varint(sock)  # packet id
        length = read_varint(sock)
        data = b""
        while len(data) < length:
            chunk = sock.recv(length - len(data))
            if not chunk:
                break
            data += chunk
        total_ms = round((time.time() - t0) * 1000)
    finally:
        sock.close()
    j = json.loads(data.decode("utf-8", "replace"))
    players = j.get("players", {}) or {}
    version = j.get("version", {}) or {}
    return {
        "online": True,
        "connect_ms": connect_ms,
        "status_ms": total_ms,
        "version": version.get("name"),
        "protocol": version.get("protocol"),
        "players_online": players.get("online"),
        "players_max": players.get("max"),
        "player_sample": [strip_codes(p.get("name") or "") for p in players.get("sample", []) or [] if isinstance(p, dict)],
        "motd": strip_codes(flatten_motd(j.get("description"))).strip(),
        "has_icon": "favicon" in j,
        "enforces_secure_chat": j.get("enforcesSecureChat"),
    }


def check(address):
    host, _, p = address.partition(":")
    result = {"address": address, "checked_utc": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())}
    if p:
        target, port = host, int(p)
        result["srv"] = None
    else:
        srv = srv_lookup(host)
        result["srv"] = "%s:%d" % srv if srv else None
        target, port = srv if srv else (host, DEFAULT_PORT)
    result["target"] = "%s:%d" % (target, port)
    try:
        result["ipv4"] = sorted({i[4][0] for i in socket.getaddrinfo(target, None, socket.AF_INET)})
    except socket.gaierror as e:
        result["ipv4"] = []
        result["error"] = "DNS: the name does not resolve (%s)" % e
        result["online"] = False
        return result
    try:
        result.update(status(target, port))
    except Exception as e:
        result["online"] = False
        result["error"] = "%s: %s" % (type(e).__name__, e)
    return result


def print_human(r):
    print("Address   %s" % r["address"])
    if r.get("srv"):
        print("SRV       %s" % r["srv"])
    print("Target    %s  (%s)" % (r.get("target", "-"), ", ".join(r.get("ipv4") or []) or "no IPv4"))
    if not r.get("online"):
        print("Status    OFFLINE: %s" % r.get("error", "no reply"))
        return
    print("Status    online, connect %d ms, status reply %d ms" % (r["connect_ms"], r["status_ms"]))
    print("Version   %s (protocol %s)" % (r["version"], r["protocol"]))
    print("Players   %s / %s" % (r["players_online"], r["players_max"]))
    if r["player_sample"]:
        print("Sample    %s" % ", ".join(n for n in r["player_sample"] if n))
    print("MOTD      %s" % (r["motd"].replace("\n", " | ") or "(empty)"))
    print("Icon      %s" % ("yes" if r["has_icon"] else "no (server-icon.png missing?)"))
    print("Checked   %s" % r["checked_utc"])


def read_properties(path):
    props = {}
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            props[k.strip()] = v.strip()
    return props


def lint_properties(props):
    """A few well-known server.properties settings that often cause trouble. Returns notes."""
    notes = []

    def num(key, default):
        try:
            return int(props.get(key, default))
        except ValueError:
            return default

    if props.get("online-mode", "true").lower() == "false":
        notes.append(("high", "online-mode=false: anyone can join under any name, including yours. "
                      "Keep it true unless the server sits behind a proxy (Velocity/BungeeCord) that checks accounts."))
    if props.get("enable-rcon", "false").lower() == "true":
        pw = props.get("rcon.password", "")
        if len(pw) < 16:
            notes.append(("high", "enable-rcon=true with a short or empty rcon.password. Use a long random "
                          "password, or turn rcon off if you do not use it."))
        else:
            notes.append(("info", "enable-rcon=true: make sure rcon.port is not reachable from the internet."))
    if props.get("white-list", "false").lower() == "false" and num("max-players", 20) <= 10:
        notes.append(("medium", "white-list=false on a small server: anyone who finds the address can join. "
                      "For a friends server, turn the whitelist on (and enforce-whitelist=true)."))
    vd, sd = num("view-distance", 10), num("simulation-distance", 10)
    if vd > 12:
        notes.append(("medium", "view-distance=%d: every step above 10 adds many chunks per player. "
                      "8-10 is usually enough; lag on join or when flying often comes from here." % vd))
    if sd > 10:
        notes.append(("medium", "simulation-distance=%d: chunks that tick cost CPU every tick. "
                      "6-8 keeps farms working and the server smoother." % sd))
    if sd > vd:
        notes.append(("low", "simulation-distance (%d) is higher than view-distance (%d); it has no use above it." % (sd, vd)))
    if props.get("enable-command-block", "false").lower() == "true":
        notes.append(("info", "enable-command-block=true: fine if you use them, otherwise turn it off."))
    if num("spawn-protection", 16) > 0 and props.get("white-list", "false").lower() == "true":
        notes.append(("low", "spawn-protection=%d on a whitelisted server: non-operators cannot build near spawn. "
                      "Set 0 if that surprises your players." % num("spawn-protection", 16)))
    if props.get("enforce-secure-profile", "true").lower() == "false":
        notes.append(("info", "enforce-secure-profile=false: players without signed chat can join; "
                      "this is a choice, not an error."))
    return notes


def main():
    ap = argparse.ArgumentParser(description="Check a Minecraft Java server from the outside.")
    ap.add_argument("address", nargs="?", help="host or host:port")
    ap.add_argument("--json", action="store_true", help="print JSON")
    ap.add_argument("--properties", metavar="FILE", help="also read a server.properties file (stays on your machine)")
    a = ap.parse_args()
    if not a.address and not a.properties:
        ap.error("give an address, --properties FILE, or both")
    notes = lint_properties(read_properties(a.properties)) if a.properties else None
    if not a.address:
        if a.json:
            print(json.dumps([{"level": l, "note": n} for l, n in notes], indent=2))
        else:
            print_notes(notes)
        sys.exit(0)
    r = check(a.address)
    if notes is not None:
        r["properties_notes"] = [{"level": l, "note": n} for l, n in notes]
    if a.json:
        print(json.dumps(r, indent=2, ensure_ascii=False))
    else:
        print_human(r)
        if notes is not None:
            print()
            print_notes(notes)
    sys.exit(0 if r.get("online") else 1)


def print_notes(notes):
    print("server.properties")
    if not notes:
        print("  nothing on the short list stands out")
    order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    for level, note in sorted(notes, key=lambda x: order[x[0]]):
        print("  [%s] %s" % (level, note))


if __name__ == "__main__":
    main()
