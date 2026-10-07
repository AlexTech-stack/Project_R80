"""Vehicle backend for the QML UI: mirrors hu-vehicled's D-Bus properties.

Registered as the QML singleton `Vehicle` in module `R80.Backend`. Property
names follow the mockup's Sim.qml so the overlay Sim.qml can bind 1:1.

Uses dbus-python rather than QtDBus: PySide6 cannot demarshal a{sv} from a
QDBusArgument. On Linux Qt runs on the GLib main loop, so dbus-python's GLib
integration delivers signals inside the Qt event loop without extra threads.
"""
from __future__ import annotations

import dbus
from dbus.mainloop.glib import DBusGMainLoop
from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

SERVICE, PATH, IFACE = "de.r80.Vehicle", "/de/r80/Vehicle", "de.r80.Vehicle1"
PROPS = "org.freedesktop.DBus.Properties"

# QML name -> (D-Bus property, conversion)
MAP = {
    "speed": ("VehicleSpeed", float), "rpm": ("EngineSpeed", float), "gear": ("Gear", str),
    "outsideTemp": ("OutsideTemp", float), "oilTemp": ("OilTemp", float),
    "coolantTemp": ("CoolantTemp", float), "batteryVolt": ("BatteryVoltage", float),
    "fuelLevel": ("FuelLevel", lambda v: float(v) / 100), "rangeKm": ("Range", lambda v: int(round(v))),
    "odometer": ("Odometer", float), "tripKm": ("TripDistance", float),
    "avgConsumption": ("AvgConsumption", float), "serviceKm": ("ServiceDistance", lambda v: int(round(v))),
    "serviceDays": ("ServiceDays", lambda v: int(round(v))),
    "boost": ("BoostPressure", float), "oilPressure": ("OilPressure", float),
    "ignition": ("IgnitionState", str), "lights": ("LightState", str),
}
TYRES = ("TyrePressureFL", "TyrePressureFR", "TyrePressureRL", "TyrePressureRR")


def _py(v):
    if isinstance(v, dbus.Boolean):
        return bool(v)
    if isinstance(v, dbus.String):
        return str(v)
    if isinstance(v, dbus.Dictionary):
        return {str(k): _py(x) for k, x in v.items()}
    if isinstance(v, dbus.Array):
        return [_py(x) for x in v]
    if isinstance(v, (dbus.Double,)):
        return float(v)
    if isinstance(v, (dbus.Int32, dbus.Int64, dbus.UInt32, dbus.Byte)):
        return int(v)
    return v


class Vehicle(QObject):
    valuesChanged = Signal()
    linkChanged = Signal()
    powerChanged = Signal()
    dimChanged = Signal()
    input = Signal(str, int)       # kind, value (see hu-vehicled)
    volumeStep = Signal(int)
    muteToggled = Signal()

    def __init__(self, system_bus=False, parent=None):
        super().__init__(parent)
        self._raw = {}
        self._v = {k: (0 if conv is not str else "") for k, (_, conv) in MAP.items()}
        self._v["gear"] = "P"
        self._tyres = [0.0, 0.0, 0.0, 0.0]
        self._link = False
        self._power = "off"
        self._dim = 100
        self._night = False
        self._stale = []
        DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus() if system_bus else dbus.SessionBus()
        self.bus.add_signal_receiver(self._on_props, "PropertiesChanged", PROPS, None, PATH)
        self.bus.add_signal_receiver(self._on_input, "Input", IFACE, None, PATH)
        # Pick up the full state at start and whenever hu-vehicled (re)appears.
        self._poll = QTimer(self, interval=2000, timeout=self.refresh)
        self._poll.start()
        QTimer.singleShot(0, self.refresh)

    # ---- D-Bus ----------------------------------------------------------
    @Slot()
    def refresh(self):
        self.bus.call_async(SERVICE, PATH, PROPS, "GetAll", "s", (IFACE,),
                            self._apply, self._on_gone, timeout=1.0)

    def _on_gone(self, _err):
        if self._link:
            self._link = False       # service gone: fall back to the mockup's own data
            self.linkChanged.emit()

    def _on_props(self, iface, changed, _invalidated):
        if iface == IFACE:
            self._apply(changed)

    def _on_input(self, kind, value):
        self.input.emit(str(kind), int(value))

    def _apply(self, changed: dict):
        changed = {str(k): _py(v) for k, v in changed.items()}
        self._raw.update(changed)
        values = False
        for qml, (dbus_name, conv) in MAP.items():
            if dbus_name in changed:
                try:
                    self._v[qml] = conv(changed[dbus_name])
                    values = True
                except (TypeError, ValueError):
                    pass
        if any(t in changed for t in TYRES):
            self._tyres = [float(self._raw.get(t, 0.0)) for t in TYRES]
            values = True
        if "StaleSignals" in changed:
            self._stale = list(changed["StaleSignals"])
            values = True
        if values:
            self.valuesChanged.emit()
        if "LinkUp" in changed and bool(changed["LinkUp"]) != self._link:
            self._link = bool(changed["LinkUp"])
            self.linkChanged.emit()
        if "Power" in changed and changed["Power"] != self._power:
            self._power = str(changed["Power"])
            self.powerChanged.emit()
        if "DimLevel" in changed or "Night" in changed:
            self._dim = int(self._raw.get("DimLevel", self._dim))
            self._night = bool(self._raw.get("Night", self._night))
            self.dimChanged.emit()

    # ---- QML properties ---------------------------------------------------
    def _getter(name):  # noqa: N805 (class-body helper)
        return lambda self: self._v[name]

    speed = Property(float, _getter("speed"), notify=valuesChanged)
    rpm = Property(float, _getter("rpm"), notify=valuesChanged)
    gear = Property(str, _getter("gear"), notify=valuesChanged)
    outsideTemp = Property(float, _getter("outsideTemp"), notify=valuesChanged)
    oilTemp = Property(float, _getter("oilTemp"), notify=valuesChanged)
    coolantTemp = Property(float, _getter("coolantTemp"), notify=valuesChanged)
    batteryVolt = Property(float, _getter("batteryVolt"), notify=valuesChanged)
    fuelLevel = Property(float, _getter("fuelLevel"), notify=valuesChanged)
    rangeKm = Property(int, _getter("rangeKm"), notify=valuesChanged)
    odometer = Property(float, _getter("odometer"), notify=valuesChanged)
    tripKm = Property(float, _getter("tripKm"), notify=valuesChanged)
    avgConsumption = Property(float, _getter("avgConsumption"), notify=valuesChanged)
    serviceKm = Property(int, _getter("serviceKm"), notify=valuesChanged)
    serviceDays = Property(int, _getter("serviceDays"), notify=valuesChanged)
    boost = Property(float, _getter("boost"), notify=valuesChanged)
    oilPressure = Property(float, _getter("oilPressure"), notify=valuesChanged)
    ignition = Property(str, _getter("ignition"), notify=valuesChanged)
    lights = Property(str, _getter("lights"), notify=valuesChanged)
    tyres = Property("QVariantList", lambda self: self._tyres, notify=valuesChanged)
    staleSignals = Property("QVariantList", lambda self: self._stale, notify=valuesChanged)
    linkUp = Property(bool, lambda self: self._link, notify=linkChanged)
    power = Property(str, lambda self: self._power, notify=powerChanged)
    dimLevel = Property(int, lambda self: self._dim, notify=dimChanged)
    night = Property(bool, lambda self: self._night, notify=dimChanged)
    del _getter


MEDIA_SERVICE, MEDIA_PATH, MEDIA_IFACE = "de.r80.Media", "/de/r80/Media", "de.r80.Media1"


class Media(QObject):
    """QML singleton mirroring hu-mediad (de.r80.Media1) property names.

    Exposes the same names the mockup's Sim.qml uses for media so the overlay
    Sim.qml can bind 1:1: tracks, trackIndex, trackPos, playing, shuffle,
    repeatAll, mediaSource. `available` tells the overlay whether to fall back
    to its own simulated playlist.
    """
    changed = Signal()
    availableChanged = Signal()

    def __init__(self, system_bus=False, parent=None):
        super().__init__(parent)
        self._available = False
        self._tracks = []
        self._meta = {"title": "", "artist": "", "album": "", "duration": 0}
        self._v = {"trackIndex": 0, "trackPos": 0, "playing": False, "shuffle": False,
                   "repeatAll": True, "mediaSource": "", "trackCount": 0}
        DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus() if system_bus else dbus.SessionBus()
        self.bus.add_signal_receiver(self._on_props, "PropertiesChanged", PROPS, None, MEDIA_PATH)
        self.bus.add_signal_receiver(self._on_seeked, "Seeked", MEDIA_IFACE, None, MEDIA_PATH)
        self._poll = QTimer(self, interval=3000, timeout=self.refresh)
        self._poll.start()
        QTimer.singleShot(0, self.refresh)

    # ---- D-Bus ----------------------------------------------------------
    def refresh(self):
        self.bus.call_async(MEDIA_SERVICE, MEDIA_PATH, PROPS, "GetAll", "s", (MEDIA_IFACE,),
                            self._apply, self._on_gone, timeout=1.0)

    def _on_gone(self, _err):
        if self._available:
            self._available = False
            self.availableChanged.emit()
            self.changed.emit()

    def _on_props(self, iface, changed, _invalidated):
        if iface == MEDIA_IFACE:
            self._apply(changed)

    def _on_seeked(self, position):
        self._v["trackPos"] = int(position) // 1_000_000
        self.changed.emit()

    def _apply(self, changed: dict):
        changed = {str(k): _py(v) for k, v in changed.items()}
        if not self._available:
            self._available = True
            self.availableChanged.emit()
        if "Metadata" in changed:
            self._meta = changed["Metadata"]
        if "Playlist" in changed:
            self._tracks = list(changed["Playlist"])
        if "TrackIndex" in changed:
            self._v["trackIndex"] = int(changed["TrackIndex"])
        if "TrackCount" in changed:
            self._v["trackCount"] = int(changed["TrackCount"])
        if "Position" in changed:
            self._v["trackPos"] = int(changed["Position"]) // 1_000_000
        if "PlaybackStatus" in changed:
            self._v["playing"] = str(changed["PlaybackStatus"]) == "playing"
        if "Shuffle" in changed:
            self._v["shuffle"] = bool(changed["Shuffle"])
        if "RepeatAll" in changed:
            self._v["repeatAll"] = bool(changed["RepeatAll"])
        if "Source" in changed:
            self._v["mediaSource"] = str(changed["Source"])
        self.changed.emit()

    def _call(self, method, signature="", args=()):
        self.bus.call_async(MEDIA_SERVICE, MEDIA_PATH, MEDIA_IFACE, method,
                            signature, args, lambda *_: None, lambda *_: None, timeout=1.0)

    # ---- QML properties ---------------------------------------------------
    available = Property(bool, lambda self: self._available, notify=availableChanged)
    tracks = Property("QVariantList", lambda self: self._tracks, notify=changed)
    playing = Property(bool, lambda self: self._v["playing"], notify=changed)
    trackIndex = Property(int, lambda self: self._v["trackIndex"], notify=changed)
    trackPos = Property(int, lambda self: self._v["trackPos"], notify=changed)
    shuffle = Property(bool, lambda self: self._v["shuffle"], notify=changed)
    repeatAll = Property(bool, lambda self: self._v["repeatAll"], notify=changed)
    mediaSource = Property(str, lambda self: self._v["mediaSource"], notify=changed)
    trackCount = Property(int, lambda self: self._v["trackCount"], notify=changed)

    # ---- QML methods ------------------------------------------------------
    @Slot()
    def playPause(self):
        self._call("PlayPause")

    @Slot(bool)
    def setPlaying(self, playing):
        self._call("SetPlaying", "b", (bool(playing),))

    @Slot()
    def next(self):
        self._call("Next")

    @Slot()
    def prev(self):
        self._call("Previous")

    @Slot(int)
    def setTrack(self, index):
        self._call("SetTrack", "i", (int(index),))

    @Slot(int)
    def setPosition(self, seconds):
        self._call("SetPosition", "x", (int(seconds) * 1_000_000,))

    @Slot(bool)
    def setShuffle(self, on):
        self._call("SetShuffle", "b", (bool(on),))

    @Slot(bool)
    def setRepeatAll(self, on):
        self._call("SetRepeatAll", "b", (bool(on),))

    @Slot(str)
    def setSource(self, source):
        self._call("SetSource", "s", (str(source),))
