"""A service's part in the shutdown (decision D12): register with hu-sysd as a "saver",
save when sysd sends PrepareForShutdown, then tell sysd. Registers again whenever sysd
(re)starts. Without sysd on the bus nothing happens (vehicled then acknowledges itself).

    from saver import register_saver
    register_saver(bus, "audiod", self.save_now)      # save_now() writes the state at once

Needs a dbus-python bus with a GLib main loop.
"""
from __future__ import annotations

import dlt

log = dlt.context("SAVE", "Saving before a shutdown")
SYSTEM = ("de.r80.System", "/de/r80/System", "de.r80.System1")


def register_saver(bus, name: str, save):
    def register():
        bus.call_async(SYSTEM[0], SYSTEM[1], SYSTEM[2], "RegisterSaver", "s", (name,),
                       lambda *_: None, lambda e: log.error(f"could not register with sysd: {e}"), timeout=2.0)

    def prepare():
        try:
            save()
        except Exception as e:                          # a failed save must not block the shutdown
            log.error(f"saving before shutdown failed: {e}")
        bus.call_async(SYSTEM[0], SYSTEM[1], SYSTEM[2], "Saved", "s", (name,),
                       lambda *_: None, lambda *_: None, timeout=2.0)

    def on_owner(_name, _old, new):
        if new:
            register()

    bus.add_signal_receiver(prepare, "PrepareForShutdown", SYSTEM[2], None, SYSTEM[1])
    bus.add_signal_receiver(on_owner, "NameOwnerChanged", "org.freedesktop.DBus",
                            "org.freedesktop.DBus", "/org/freedesktop/DBus", arg0=SYSTEM[0])
    if bus.name_has_owner(SYSTEM[0]):
        register()
