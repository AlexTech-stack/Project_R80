#!/usr/bin/env python3
"""TC_HU_042: the system's own log in DLT (hu-syslogd, syslog.ini). Journal entries (the virtual
mode's stand-in journal, made-up lines only) of the configured sources arrive as the DLT
application OS, one context per source, at their level; other sources and lines below a
source's level do not. Cleaned first: a Bluetooth address keeps its last two bytes (also
BlueZ's dev_AA_BB_... form), a phone number becomes <number>, a line with a name is left out,
NetworkManager's quoted names become '…'; none of them is anywhere in the stream. The same
line many times within 10 s is written once, then once more with how often it came. A system
warning is counted on the Diagnostics page (sysd); a log level set through sysd reaches the
source (debug: PipeWire's info lines come through, back to default)."""
import time

from common import DLT_PORT, DltStream, check, finish, journal, sys_props, system

ADDR = "5A:3C:00:11:7E:42"              # made up
NUMBER = "+49 170 5550123"              # made up
NAME = "Testphone Zebra"
SSID = "Testnet Quokka"
CONTEXTS = {"MAIN", "KERN", "BT", "PW", "NET", "UNIT", "SYSD"}


def app_view(apid):
    return next((a for a in sys_props()["Log"]["apps"] if a["id"] == apid), {})


def texts(dlt, ctid=None):
    with dlt.lock:
        return [m.text for m in dlt.messages if m.apid == "OS" and (ctid is None or m.ctid == ctid)]


def sent(dlt, ctid, word, timeout=4.0):
    return dlt.wait(lambda m: m.apid == "OS" and m.ctid == ctid and word in m.text, timeout)


try:
    dlt = DltStream()
except OSError as e:
    check(False, f"the DLT daemon answers on TCP {DLT_PORT} ({e})")
    finish()

info = {}
for _ in range(20):
    info = dlt.log_info()
    if "OS" in info:
        break
    time.sleep(0.3)
ctx = info.get("OS", {}).get("contexts", {})
check(CONTEXTS <= set(ctx), f"syslogd is the DLT application OS, a context per source ({sorted(ctx)})")
check(ctx.get("PW", {}).get("level") == 3 and ctx.get("BT", {}).get("level") == 4,
      f"... at the levels of syslog.ini (PipeWire warning, BlueZ info: {ctx.get('PW', {}).get('level')}, "
      f"{ctx.get('BT', {}).get('level')})")
system().ClearLog()
tag = f"t{int(time.time())}"            # this run's lines

# --- the sources, their contexts and levels
journal(f"{tag} usb 1-1: device descriptor read/64, error -71", 3, _TRANSPORT="kernel")
m = sent(dlt, "KERN", tag)
check(m is not None and m.level == 2, f"a kernel error: OS KERN, error ({m})")
journal(f"{tag} cannelloni up", 6, _SYSTEMD_UNIT="r80-can.service")
journal(f"{tag} r80-can.service: Failed with result 'exit-code'.", 4, SYSLOG_IDENTIFIER="systemd")
check(sent(dlt, "UNIT", tag) is not None and sent(dlt, "SYSD", tag) is not None,
      "the HU's own units (UNIT) and systemd's failed units (SYSD)")
journal(f"{tag} PipeWire info, not wanted", 6, SYSLOG_IDENTIFIER="wireplumber")
journal(f"{tag} sshd line, not ours", 3, SYSLOG_IDENTIFIER="sshd")
journal(f"{tag} kernel info, not wanted", 6, _TRANSPORT="kernel")
journal(f"{tag} marker", 4, SYSLOG_IDENTIFIER="pipewire")
check(sent(dlt, "PW", f"{tag} marker") is not None, "a PipeWire warning: OS PW")
check(not any("not wanted" in t or "not ours" in t for t in texts(dlt)),
      "below a source's level and other sources (sshd): not written")

# --- cleaning
journal(f"{tag} /org/bluez/hci0/dev_{ADDR.replace(':', '_')}/fd0: fd(32) ready", 6, SYSLOG_IDENTIFIER="bluetoothd")
m = sent(dlt, "BT", f"{tag} /org/bluez")
check(m is not None and "dev_..:7E:42/fd0" in m.text, f"BlueZ's device path: the address keeps its last two bytes ({m and m.text})")
journal(f"{tag} Bluetooth: hci0: link to {ADDR.lower()} lost", 4, _TRANSPORT="kernel")
m = sent(dlt, "KERN", f"{tag} Bluetooth")
check(m is not None and "..:7E:42" in m.text, f"... also in the AA:BB form, any case ({m and m.text})")
journal(f"{tag} call from {NUMBER} failed", 4, SYSLOG_IDENTIFIER="wireplumber")
m = sent(dlt, "PW", f"{tag} call from")
check(m is not None and m.text.endswith("call from <number> failed"), f"a phone number: <number> ({m and m.text})")
journal(f"{tag} device {ADDR}: Name: {NAME}", 6, SYSLOG_IDENTIFIER="bluetoothd")
m = sent(dlt, "BT", "left out")
check(m is not None, f"a line with a name: left out ({m and m.text})")
journal(f"{tag} device (wlan0): Activation: connection '{SSID}' failed", 4, SYSLOG_IDENTIFIER="NetworkManager")
m = sent(dlt, "NET", f"{tag} device (wlan0)")
check(m is not None and "connection '…' failed" in m.text, f"NetworkManager: quoted names '…' ({m and m.text})")
time.sleep(0.5)
everything = "\n".join(texts(dlt))
check(not any(s in everything or s.lower() in everything for s in (ADDR, ADDR.replace(":", "_"), NUMBER, NAME, SSID)),
      "no address, number, device or network name anywhere in the stream")

# --- repeats
for _ in range(30):
    journal(f"{tag} Bluetooth: hci0: Frame reassembly failed (-84)", 3, _TRANSPORT="kernel")
m = sent(dlt, "KERN", "(and 29 more times in 10 s)", timeout=14.0)
lines = [t for t in texts(dlt, "KERN") if f"{tag} Bluetooth: hci0: Frame" in t]
check(m is not None and len(lines) == 2, f"30 times the same line: written once, then 'and 29 more times' ({len(lines)} lines)")

# --- Diagnostics and log levels
v = app_view("OS")
check(v.get("running") and v.get("errors", 0) >= 2 and v.get("warnings", 0) >= 3,
      f"Diagnostics: OS running, its errors and warnings counted ({v})")
s = system()
s.SetLogLevel("OS", "debug")
time.sleep(1.0)
journal(f"{tag} PipeWire info, now wanted", 6, SYSLOG_IDENTIFIER="wireplumber")
check(sent(dlt, "PW", "now wanted") is not None, "SetLogLevel OS debug: PipeWire's info lines come through")
s.SetLogLevel("OS", "default")
time.sleep(1.0)
journal(f"{tag} PipeWire debug, not wanted again", 7, SYSLOG_IDENTIFIER="wireplumber")
time.sleep(1.0)
check(not any("not wanted again" in t for t in texts(dlt)), "back to default: no debug lines")
finish()
