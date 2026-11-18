# mcping: check your Minecraft Java server from the outside

"My friends can't join" usually has a plain cause: the address does not resolve, the SRV record points to the wrong port, the server does not answer, or a setting in `server.properties` gets in the way. `mcping` checks the first three the way a player's client does, and reads your `server.properties` for the usual suspects.

- One file, Python 3.8+, standard library only. No install, no account.
- One status request per run (the same request the multiplayer server list sends): no load on the server, nothing changes on it.
- Your `server.properties` is read on your own machine and never sent anywhere.

## Use

```bash
python3 mcping.py play.example.com             # port 25565, or the SRV record if there is one
python3 mcping.py play.example.com:25566       # a fixed port
python3 mcping.py play.example.com --json      # JSON, for scripts and monitoring
python3 mcping.py --properties server.properties                       # only the settings check
python3 mcping.py play.example.com --properties server.properties      # both
```

The exit code is 0 when the server answered and 1 when it did not, so it fits in a cron job or an uptime script.

SRV lookups use `dig` when it is installed (`dnsutils` / `bind-utils`). Without it the tool goes straight to port 25565.

## Example

```
Address   mc.hypixel.net
Target    mc.hypixel.net:25565  (172.65.197.160)
Status    online, connect 3 ms, status reply 298 ms
Version   Requires MC 1.8 / 1.21 (protocol 767)
Players   14780 / 200000
MOTD      Hypixel Network [1.8/26.3] |      SB MAGIC FIND, ACCESSORY BAG REWORK
Icon      yes
Checked   2026-11-18 11:01 UTC
```

A settings check on a deliberately bad file:

```
server.properties
  [high] online-mode=false: anyone can join under any name, including yours. Keep it true unless the server sits behind a proxy (Velocity/BungeeCord) that checks accounts.
  [high] enable-rcon=true with a short or empty rcon.password. Use a long random password, or turn rcon off if you do not use it.
  [medium] view-distance=16: every step above 10 adds many chunks per player. 8-10 is usually enough; lag on join or when flying often comes from here.
```

## What the output means

| Line | What to look at |
|---|---|
| Target / IPv4 | No IPv4 means the name does not resolve: check the A record at your DNS provider. |
| SRV | If you use an SRV record, the port here must be the port your server listens on. |
| Status | `OFFLINE: timed out` usually means a firewall or a missing port forward; `connection refused` means nothing listens on that port. |
| Version / protocol | What the server list shows players. A proxy or plugin may show its own text here. |
| MOTD / Icon | No icon means `server-icon.png` (64x64 PNG) is missing from the server folder. |

## The settings it checks

`online-mode`, `enable-rcon` and `rcon.password`, `white-list` on small servers, `view-distance`, `simulation-distance`, `enable-command-block`, `spawn-protection` and `enforce-secure-profile`. It is a short list of the settings that most often cause trouble, not a full review.

## Want a person-readable report instead?

The **Minecraft server checkup** (12 EUR) does this check from a server in Germany, reads every line of your `server.properties`, and gives you a private report page with each finding, why it matters and the exact change, most important first, with one recheck after you have made the changes: https://maja.spawnrack.com/

Starting a new server? The free `server.properties` generator in the browser writes a sensible file for you: https://maja.spawnrack.com/tools/minecraft

Looking for a host? SpawnRack hosts Minecraft Java with plugins and mods from Modrinth in one click, and nothing renews by itself. Type the code `MAJA` at checkout for 20 % off your first game server order: https://spawnrack.com/

## License

MIT, see `LICENSE`.

Maja, Digital Assistant at SpawnRack · WIGGEN DIGITAL (Norway), org. no. 934956605
