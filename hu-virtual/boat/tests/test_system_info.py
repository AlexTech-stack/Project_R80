#!/usr/bin/env python3
"""TC_HU_028: system information for Settings -> System (hu-sysd's Info): every HU service
of [info] services in system.ini is reported running in the virtual environment, the facts
about the computer are plausible (version, OS, uptime, memory, storage), they are refreshed
every refresh_s, and the Bluetooth fields are there (an adapter or none)."""
import time

from common import check, finish, sys_logic, sys_props

sysd, cfg = sys_logic()
expected = cfg["info"]["services"]

t0 = time.monotonic()
info = {}
while time.monotonic() - t0 < 10:
    info = sys_props()["Info"]
    if sorted(info.get("services_up", [])) == sorted(expected):
        break
    time.sleep(0.5)
check(sorted(info.get("services_up", [])) == sorted(expected) and not info.get("services_missing"),
      f"all {len(expected)} HU services reported running (missing: {info.get('services_missing')})")
check(info.get("version") not in (None, "", "unknown"), f"software version: {info.get('version')}")
check(info.get("os") not in (None, "") and info.get("kernel"), f"OS and kernel: {info.get('os')} / {info.get('kernel')}")
check(info.get("uptime_s", -1) > 0, f"uptime {info.get('uptime_s')} s")
check(0 < info.get("mem_available_mb", -1) <= info.get("mem_total_mb", -1),
      f"memory {info.get('mem_available_mb')} of {info.get('mem_total_mb')} MB available")
check(info.get("disk_free_mb", -1) >= 0, f"storage {info.get('disk_free_mb')} MB free")
check(all(k in info for k in ("bt_name", "bt_address", "bt_powered", "cpu_temp_c", "load")),
      f"Bluetooth and CPU fields present (adapter: {info.get('bt_name') or 'none'})")

first = info["uptime_s"]
time.sleep(cfg["info"]["refresh_s"] + 1.5)
later = sys_props()["Info"]["uptime_s"]
check(later > first, f"refreshed every {cfg['info']['refresh_s']:g} s (uptime {first} -> {later})")
finish()
