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

import dlt                                    # hu/services/dlt.py; run.py puts it on sys.path

log = dlt.context("MAIN", "User interface")

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

    The playing track (track), the queue (trackIndex, trackCount, queueTitle, upNext:
    the next tracks in play order), playing, trackPos, shuffle, repeatAll, the sources,
    and browsing: browse() answers with browsed(), playFrom() plays a list. A cover is
    a file path ("" = none), shown through covers.py. `available` tells Sim.qml
    whether to fall back to its demo playlist.
    """
    changed = Signal()
    availableChanged = Signal()
    browsed = Signal(str, int, str, int, "QVariantList")   # path, offset, title, total, entries

    def __init__(self, system_bus=False, parent=None):
        super().__init__(parent)
        self._available = False
        self._sources = []
        self._up_next = []
        self._meta = {"title": "", "artist": "", "album": "", "trackNumber": 0, "duration": 0, "cover": ""}
        self._v = {"trackIndex": 0, "trackPos": 0, "playing": False, "shuffle": False,
                   "repeatAll": True, "mediaSource": "", "trackCount": 0, "queueTitle": "", "queue": "",
                   "sourceTrackCount": 0, "scanned": 0}
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
        if "UpNext" in changed:
            self._up_next = list(changed["UpNext"])
        for name, key in (("QueueTitle", "queueTitle"), ("Queue", "queue")):
            if name in changed:
                self._v[key] = str(changed[name])
        for name, key in (("SourceTrackCount", "sourceTrackCount"), ("Scanned", "scanned")):
            if name in changed:
                self._v[key] = int(changed[name])
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
        if "Sources" in changed:
            self._sources = [str(x) for x in changed["Sources"]]
        self.changed.emit()

    def _call(self, method, signature="", args=()):
        self.bus.call_async(MEDIA_SERVICE, MEDIA_PATH, MEDIA_IFACE, method,
                            signature, args, lambda *_: None, lambda *_: None, timeout=1.0)

    # ---- QML properties ---------------------------------------------------
    available = Property(bool, lambda self: self._available, notify=availableChanged)
    track = Property("QVariantMap", lambda self: self._meta, notify=changed)
    upNext = Property("QVariantList", lambda self: self._up_next, notify=changed)
    queueTitle = Property(str, lambda self: self._v["queueTitle"], notify=changed)
    queue = Property(str, lambda self: self._v["queue"], notify=changed)
    sourceTrackCount = Property(int, lambda self: self._v["sourceTrackCount"], notify=changed)
    scanned = Property(int, lambda self: self._v["scanned"], notify=changed)
    playing = Property(bool, lambda self: self._v["playing"], notify=changed)
    trackIndex = Property(int, lambda self: self._v["trackIndex"], notify=changed)
    trackPos = Property(int, lambda self: self._v["trackPos"], notify=changed)
    shuffle = Property(bool, lambda self: self._v["shuffle"], notify=changed)
    repeatAll = Property(bool, lambda self: self._v["repeatAll"], notify=changed)
    mediaSource = Property(str, lambda self: self._v["mediaSource"], notify=changed)
    trackCount = Property(int, lambda self: self._v["trackCount"], notify=changed)
    sources = Property("QVariantList", lambda self: self._sources, notify=changed)

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

    @Slot(str, int, int)
    def browse(self, path, offset, count):
        """Ask mediad for a page of a list; the answer comes as browsed(...)."""
        def done(title, total, entries):
            self.browsed.emit(path, offset, str(title), int(total), [_py(e) for e in entries])

        def failed(_err):
            self.browsed.emit(path, offset, "", -1, [])        # total -1: no such list
        self.bus.call_async(MEDIA_SERVICE, MEDIA_PATH, MEDIA_IFACE, "Browse", "sii",
                            (str(path), int(offset), int(count)), done, failed, timeout=5.0)

    @Slot(str, int)
    def playFrom(self, path, index):
        self._call("PlayFrom", "si", (str(path), int(index)))


AUDIO_SERVICE, AUDIO_PATH, AUDIO_IFACE = "de.r80.Audio", "/de/r80/Audio", "de.r80.Audio1"


class Audio(QObject):
    """QML singleton mirroring hu-audiod (de.r80.Audio1): master volume, mute and the
    per-source volumes. audiod owns them; the UI only shows them and asks for changes.
    `available` tells the overlay Sim.qml whether to fall back to its own volume."""
    changed = Signal()
    availableChanged = Signal()

    def __init__(self, system_bus=False, parent=None):
        super().__init__(parent)
        self._available = False
        self._v = {"master": 0, "muted": False, "max": 30, "volumes": {}, "tone": {}}
        DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus() if system_bus else dbus.SessionBus()
        self.bus.add_signal_receiver(self._on_props, "PropertiesChanged", PROPS, None, AUDIO_PATH)
        self._poll = QTimer(self, interval=3000, timeout=self.refresh)
        self._poll.start()
        QTimer.singleShot(0, self.refresh)

    def refresh(self):
        self.bus.call_async(AUDIO_SERVICE, AUDIO_PATH, PROPS, "GetAll", "s", (AUDIO_IFACE,),
                            self._apply, self._on_gone, timeout=1.0)

    def _on_gone(self, _err):
        if self._available:
            self._available = False
            self.availableChanged.emit()
            self.changed.emit()

    def _on_props(self, iface, changed, _invalidated):
        if iface == AUDIO_IFACE:
            self._apply(changed)

    def _apply(self, changed: dict):
        changed = {str(k): _py(v) for k, v in changed.items()}
        if not self._available:
            self._available = True
            self.availableChanged.emit()
        for key, prop in (("Master", "master"), ("Muted", "muted"), ("Max", "max"), ("Volumes", "volumes"), ("Tone", "tone")):
            if key in changed:
                self._v[prop] = changed[key]
        self.changed.emit()

    def _call(self, method, signature="", args=()):
        self.bus.call_async(AUDIO_SERVICE, AUDIO_PATH, AUDIO_IFACE, method,
                            signature, args, lambda *_: None, lambda *_: None, timeout=1.0)

    available = Property(bool, lambda self: self._available, notify=availableChanged)
    master = Property(int, lambda self: int(self._v["master"]), notify=changed)
    muted = Property(bool, lambda self: bool(self._v["muted"]), notify=changed)
    max = Property(int, lambda self: int(self._v["max"]), notify=changed)
    volumes = Property("QVariantMap", lambda self: dict(self._v["volumes"]), notify=changed)
    tone = Property("QVariantMap", lambda self: dict(self._v["tone"]), notify=changed)

    @Slot(str, "QVariant")
    def setTone(self, name, value):
        """bass / treble (whole dB), balance (-1..1), loudness (bool); audiod checks the range."""
        v = (dbus.Boolean(value) if isinstance(value, bool) else dbus.Double(value) if name == "balance"
             else dbus.Int32(int(round(value))))
        self._call("SetTone", "sv", (str(name), v))

    @Slot(int)
    def setMaster(self, value):
        self._call("SetMaster", "i", (int(value),))

    @Slot(bool)
    def setMuted(self, muted):
        self._call("SetMuted", "b", (bool(muted),))

    @Slot(str, int)
    def setVolume(self, source, value):
        self._call("SetVolume", "si", (str(source), int(value)))

    @Slot(str)
    def setCallState(self, state):
        """Stand-in for the phone service: the UI's simulated call (idle|ringing|active)."""
        self._call("SetCallState", "s", (str(state),))


WARN_SERVICE, WARN_PATH, WARN_IFACE = "de.r80.Warnings", "/de/r80/Warnings", "de.r80.Warnings1"


class Warnings(QObject):
    """QML singleton mirroring hu-warnd (de.r80.Warnings1): the active vehicle warnings,
    most urgent first, as dicts {id, severity, text, acknowledged, since}. `available`
    tells the overlay Sim.qml whether to fall back to its own demo warnings."""
    changed = Signal()
    availableChanged = Signal()

    def __init__(self, system_bus=False, parent=None):
        super().__init__(parent)
        self._available = False
        self._active = []
        DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus() if system_bus else dbus.SessionBus()
        self.bus.add_signal_receiver(self._on_props, "PropertiesChanged", PROPS, None, WARN_PATH)
        self._poll = QTimer(self, interval=3000, timeout=self.refresh)
        self._poll.start()
        QTimer.singleShot(0, self.refresh)

    def refresh(self):
        self.bus.call_async(WARN_SERVICE, WARN_PATH, PROPS, "GetAll", "s", (WARN_IFACE,),
                            self._apply, self._on_gone, timeout=1.0)

    def _on_gone(self, _err):
        if self._available:
            self._available = False
            self._active = []
            self.availableChanged.emit()
            self.changed.emit()

    def _on_props(self, iface, changed, _invalidated):
        if iface == WARN_IFACE:
            self._apply(changed)

    def _apply(self, changed: dict):
        if not self._available:
            self._available = True
            self.availableChanged.emit()
        if "Active" in changed:
            self._active = [{str(k): _py(v) for k, v in w.items()} for w in changed["Active"]]
            self.changed.emit()

    def _call(self, method, signature="", args=()):
        self.bus.call_async(WARN_SERVICE, WARN_PATH, WARN_IFACE, method,
                            signature, args, lambda *_: None, lambda *_: None, timeout=1.0)

    available = Property(bool, lambda self: self._available, notify=availableChanged)
    active = Property("QVariantList", lambda self: list(self._active), notify=changed)

    @Slot(str)
    def acknowledge(self, rid):
        self._call("Acknowledge", "s", (str(rid),))

    @Slot()
    def acknowledgeAll(self):
        self._call("AcknowledgeAll")


TRIP_SERVICE, TRIP_PATH, TRIP_IFACE = "de.r80.Trip", "/de/r80/Trip", "de.r80.Trip1"


class Trip(QObject):
    """QML singleton mirroring hu-tripd (de.r80.Trip1): the "since start" and "long-term"
    trips as dicts {distance, time, avg_speed, max_speed, avg_consumption}."""
    changed = Signal()
    availableChanged = Signal()

    def __init__(self, system_bus=False, parent=None):
        super().__init__(parent)
        self._available = False
        self._v = {"SinceStart": {}, "LongTerm": {}}
        DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus() if system_bus else dbus.SessionBus()
        self.bus.add_signal_receiver(self._on_props, "PropertiesChanged", PROPS, None, TRIP_PATH)
        self._poll = QTimer(self, interval=3000, timeout=self.refresh)
        self._poll.start()
        QTimer.singleShot(0, self.refresh)

    def refresh(self):
        self.bus.call_async(TRIP_SERVICE, TRIP_PATH, PROPS, "GetAll", "s", (TRIP_IFACE,),
                            self._apply, self._on_gone, timeout=1.0)

    def _on_gone(self, _err):
        if self._available:
            self._available = False
            self.availableChanged.emit()
            self.changed.emit()

    def _on_props(self, iface, changed, _invalidated):
        if iface == TRIP_IFACE:
            self._apply(changed)

    def _apply(self, changed: dict):
        if not self._available:
            self._available = True
            self.availableChanged.emit()
        for k in ("SinceStart", "LongTerm"):
            if k in changed:
                self._v[k] = {str(a): _py(b) for a, b in changed[k].items()}
        self.changed.emit()

    available = Property(bool, lambda self: self._available, notify=availableChanged)
    sinceStart = Property("QVariantMap", lambda self: dict(self._v["SinceStart"]), notify=changed)
    longTerm = Property("QVariantMap", lambda self: dict(self._v["LongTerm"]), notify=changed)

    @Slot(str)
    def reset(self, which):
        self.bus.call_async(TRIP_SERVICE, TRIP_PATH, TRIP_IFACE, "Reset", "s", (str(which),),
                            lambda *_: None, lambda *_: None, timeout=1.0)


NAV_SERVICE, NAV_PATH, NAV_IFACE = "de.r80.Nav", "/de/r80/Nav", "de.r80.Nav1"


class Nav(QObject):
    """QML singleton mirroring hu-navd (de.r80.Nav1, D11): the phone link as a dict
    {connected, device, app, bad_lines}, the guidance as a dict {active, stale, source,
    maneuver, modifier, exit, distance_m, street, text, remaining_m, remaining_s, arrival},
    and from the phone the weather {valid, source, time, temp_c, code, days} and the
    position {valid, time, alt_m, accuracy_m, heading_deg}."""
    changed = Signal()
    availableChanged = Signal()

    def __init__(self, system_bus=False, parent=None):
        super().__init__(parent)
        self._available = False
        self._v = {"Phone": {}, "Guidance": {}, "Weather": {}, "Position": {}}
        DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus() if system_bus else dbus.SessionBus()
        self.bus.add_signal_receiver(self._on_props, "PropertiesChanged", PROPS, None, NAV_PATH)
        self._poll = QTimer(self, interval=3000, timeout=self.refresh)
        self._poll.start()
        QTimer.singleShot(0, self.refresh)

    def refresh(self):
        self.bus.call_async(NAV_SERVICE, NAV_PATH, PROPS, "GetAll", "s", (NAV_IFACE,),
                            self._apply, self._on_gone, timeout=1.0)

    def _on_gone(self, _err):
        if self._available:
            self._available = False
            self.availableChanged.emit()
            self.changed.emit()

    def _on_props(self, iface, changed, _invalidated):
        if iface == NAV_IFACE:
            self._apply(changed)

    def _apply(self, changed: dict):
        if not self._available:
            self._available = True
            self.availableChanged.emit()
        for k in ("Phone", "Guidance", "Weather", "Position"):
            if k in changed:
                self._v[k] = {str(a): _py(b) for a, b in changed[k].items()}
        self.changed.emit()

    available = Property(bool, lambda self: self._available, notify=availableChanged)
    phone = Property("QVariantMap", lambda self: dict(self._v["Phone"]), notify=changed)
    guidance = Property("QVariantMap", lambda self: dict(self._v["Guidance"]), notify=changed)
    weather = Property("QVariantMap", lambda self: dict(self._v["Weather"]), notify=changed)
    position = Property("QVariantMap", lambda self: dict(self._v["Position"]), notify=changed)


SYS_SERVICE, SYS_PATH, SYS_IFACE = "de.r80.System", "/de/r80/System", "de.r80.System1"


class System(QObject):
    """QML singleton mirroring hu-sysd (de.r80.System1, D12): the user's settings as a dict
    {name: value} (names as in hu/system.ini; sysd checks and saves every change), the
    display brightness sysd computes from them, day/night and the car's dimmer, the system
    information, the DLT log's warnings and errors (log: connected, apps, entries), the
    log export onto a USB stick (logExport: state, message, dir) and software updates
    (softwareUpdate: sysd's Update; installUpdate takes the one on a USB stick, restartNow,
    rollbackUpdate)."""
    changed = Signal()
    availableChanged = Signal()

    def __init__(self, system_bus=False, parent=None):
        super().__init__(parent)
        self._available = False
        self._settings = {}
        self._display = 0.9
        self._info = {}
        self._log = {}
        self._export = {}
        self._update = {}
        DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus() if system_bus else dbus.SessionBus()
        self.bus.add_signal_receiver(self._on_props, "PropertiesChanged", PROPS, None, SYS_PATH)
        self._poll = QTimer(self, interval=3000, timeout=self.refresh)
        self._poll.start()
        QTimer.singleShot(0, self.refresh)

    def refresh(self):
        self.bus.call_async(SYS_SERVICE, SYS_PATH, PROPS, "GetAll", "s", (SYS_IFACE,),
                            self._apply, self._on_gone, timeout=1.0)

    def _on_gone(self, _err):
        if self._available:
            self._available = False
            self.availableChanged.emit()
            self.changed.emit()

    def _on_props(self, iface, changed, _invalidated):
        if iface == SYS_IFACE:
            self._apply(changed)

    def _apply(self, changed: dict):
        if "Settings" in changed:
            self._settings = {str(k): _py(v) for k, v in changed["Settings"].items()}
        if "DisplayBrightness" in changed:
            self._display = float(changed["DisplayBrightness"])
        if "Info" in changed:
            self._info = {str(k): _py(v) for k, v in changed["Info"].items()}
        if "Log" in changed:
            self._log = _py(changed["Log"])
        if "Export" in changed:
            self._export = _py(changed["Export"])
        if "Update" in changed:
            self._update = _py(changed["Update"])
        if not self._available:
            self._available = True
            self.availableChanged.emit()
        self.changed.emit()

    available = Property(bool, lambda self: self._available, notify=availableChanged)
    # the live UI: Sim.qml shows "–" for what a service has not told yet (the demo stand-in says true)
    demo = Property(bool, lambda self: False, constant=True)
    settings = Property("QVariantMap", lambda self: dict(self._settings), notify=changed)
    displayBrightness = Property(float, lambda self: self._display, notify=changed)
    info = Property("QVariantMap", lambda self: dict(self._info), notify=changed)
    log = Property("QVariantMap", lambda self: dict(self._log), notify=changed)
    logExport = Property("QVariantMap", lambda self: dict(self._export), notify=changed)
    softwareUpdate = Property("QVariantMap", lambda self: dict(self._update), notify=changed)

    @Slot(str, "QVariant")
    def set(self, name, value):
        v = (dbus.Boolean(value) if isinstance(value, bool) else dbus.Double(value) if isinstance(value, (int, float))
             else dbus.String(str(value)))
        self.bus.call_async(SYS_SERVICE, SYS_PATH, SYS_IFACE, "Set", "sv", (str(name), v),
                            lambda *_: None, lambda e: log.warning(f"setting {name} refused: {e}"), timeout=1.0)

    @Slot()
    def resetAll(self):
        self.bus.call_async(SYS_SERVICE, SYS_PATH, SYS_IFACE, "ResetAll", "", (),
                            lambda *_: None, lambda *_: None, timeout=1.0)

    @Slot(str, str)
    def setLogLevel(self, app, level):
        self.bus.call_async(SYS_SERVICE, SYS_PATH, SYS_IFACE, "SetLogLevel", "ss", (str(app), str(level)),
                            lambda *_: None, lambda e: log.warning(f"log level of {app} refused: {e}"), timeout=2.0)

    @Slot()
    def exportLog(self):
        self.bus.call_async(SYS_SERVICE, SYS_PATH, SYS_IFACE, "ExportLog", "", (),
                            lambda *_: None, lambda e: log.warning(f"log export refused: {e}"), timeout=2.0)

    @Slot()
    def clearLog(self):
        self.bus.call_async(SYS_SERVICE, SYS_PATH, SYS_IFACE, "ClearLog", "", (),
                            lambda *_: None, lambda *_: None, timeout=1.0)

    def _update_call(self, method):
        self.bus.call_async(SYS_SERVICE, SYS_PATH, SYS_IFACE, method, "", (),
                            lambda *_: None, lambda e: log.warning(f"{method} refused: {e.get_dbus_message()}"), timeout=2.0)

    @Slot()
    def installUpdate(self):
        self._update_call("InstallFound")

    @Slot()
    def restartNow(self):
        self._update_call("RestartNow")

    @Slot()
    def rollbackUpdate(self):
        self._update_call("Rollback")


PHONE_SERVICE, PHONE_PATH, PHONE_IFACE = "de.r80.Phone", "/de/r80/Phone", "de.r80.Phone1"


class Phone(QObject):
    """QML singleton mirroring hu-phoned (de.r80.Phone1): the connected phone (connected,
    deviceName, battery: -1 = unknown) and its calls (callState: idle | ringing | dialing |
    active, the current call's callerName / callerNumber / callSince: unix ms it became
    active, 0 = not yet). dial / answer / hangup / sendTones go to phoned. The copy of the
    phone's contacts: consent ("" = not asked yet, yes, no), syncState (idle | syncing |
    failed), syncError, syncedAt (unix s), contactCount, contacts (all, fetched whenever the
    copy changes), history, favourites; setConsent / sync / deleteCopy / setFavourite."""
    changed = Signal()
    availableChanged = Signal()

    def __init__(self, system_bus=False, parent=None):
        super().__init__(parent)
        self._available = False
        self._v = {"Connected": False, "Device": {}, "Calls": [], "CallState": "idle", "Consent": "",
                   "SyncState": "idle", "SyncError": "", "SyncedAt": 0, "ContactCount": 0, "History": [],
                   "Favourites": [], "MicMuted": False, "MicAvailable": True}
        self._contacts = []
        self._contacts_key = None
        DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus() if system_bus else dbus.SessionBus()
        self.bus.add_signal_receiver(self._on_props, "PropertiesChanged", PROPS, None, PHONE_PATH)
        self._poll = QTimer(self, interval=3000, timeout=self.refresh)
        self._poll.start()
        QTimer.singleShot(0, self.refresh)

    def refresh(self):
        self.bus.call_async(PHONE_SERVICE, PHONE_PATH, PROPS, "GetAll", "s", (PHONE_IFACE,),
                            self._apply, self._on_gone, timeout=1.0)

    def _on_gone(self, _err):
        if self._available:
            self._available = False
            self.availableChanged.emit()
            self.changed.emit()

    def _on_props(self, iface, changed, _invalidated):
        if iface == PHONE_IFACE:
            self._apply(changed)

    def _apply(self, changed: dict):
        if not self._available:
            self._available = True
            self.availableChanged.emit()
        for k in self._v:
            if k in changed:
                self._v[k] = _py(changed[k])
        key = (self._v["Device"].get("address"), self._v["SyncedAt"], self._v["ContactCount"])
        if key != self._contacts_key:                  # the copy changed: fetch the contacts again
            self._contacts_key = key
            self.bus.call_async(PHONE_SERVICE, PHONE_PATH, PHONE_IFACE, "GetContacts", "ii",
                                (0, int(self._v["ContactCount"])), self._got_contacts, lambda e: None, timeout=10.0)
        self.changed.emit()

    def _got_contacts(self, contacts):
        self._contacts = [_py(c) for c in contacts]
        self.changed.emit()

    def _call(self) -> dict:
        """The call the UI shows: the ringing one, else the first."""
        calls = self._v["Calls"]
        return next((c for c in calls if c.get("state") in ("incoming", "waiting")), calls[0] if calls else {})

    def _send(self, method, signature="", args=()):
        self.bus.call_async(PHONE_SERVICE, PHONE_PATH, PHONE_IFACE, method, signature, args,
                            lambda *_: None, lambda e: log.warning(f"phone {method}: {e}"), timeout=30.0)

    available = Property(bool, lambda self: self._available, notify=availableChanged)
    connected = Property(bool, lambda self: bool(self._v["Connected"]), notify=changed)
    deviceName = Property(str, lambda self: str(self._v["Device"].get("name", "")), notify=changed)
    battery = Property(int, lambda self: int(self._v["Device"].get("battery", -1)), notify=changed)
    callState = Property(str, lambda self: str(self._v["CallState"]), notify=changed)
    callerName = Property(str, lambda self: str(self._call().get("name", "")), notify=changed)
    callerNumber = Property(str, lambda self: str(self._call().get("number", "")), notify=changed)
    callSince = Property(float, lambda self: float(self._call().get("since", 0)), notify=changed)
    consent = Property(str, lambda self: str(self._v["Consent"]), notify=changed)
    syncState = Property(str, lambda self: str(self._v["SyncState"]), notify=changed)
    syncError = Property(str, lambda self: str(self._v["SyncError"]), notify=changed)
    syncedAt = Property(float, lambda self: float(self._v["SyncedAt"]), notify=changed)
    contactCount = Property(int, lambda self: int(self._v["ContactCount"]), notify=changed)
    contacts = Property("QVariantList", lambda self: self._contacts, notify=changed)
    history = Property("QVariantList", lambda self: list(self._v["History"]), notify=changed)
    favourites = Property("QVariantList", lambda self: list(self._v["Favourites"]), notify=changed)
    micMuted = Property(bool, lambda self: bool(self._v["MicMuted"]), notify=changed)
    micAvailable = Property(bool, lambda self: bool(self._v["MicAvailable"]), notify=changed)

    @Slot(str)
    def dial(self, number):
        self._send("Dial", "s", (str(number),))

    @Slot()
    def answer(self):
        self._send("Answer")

    @Slot()
    def hangup(self):
        self._send("Hangup")

    @Slot(str)
    def sendTones(self, tones):
        self._send("SendTones", "s", (str(tones),))

    @Slot(bool)
    def setMicMuted(self, muted):
        self._send("SetMicMuted", "b", (bool(muted),))

    @Slot(bool)
    def setConsent(self, allowed):
        self._send("SetConsent", "b", (bool(allowed),))

    @Slot()
    def sync(self):
        self._send("Sync")

    @Slot()
    def deleteCopy(self):
        self._send("DeleteCopy")

    @Slot(str, bool)
    def setFavourite(self, contact_id, on):
        self._send("SetFavourite", "sb", (str(contact_id), bool(on)))


AST_SERVICE, AST_PATH, AST_IFACE = "de.r80.Assistant", "/de/r80/Assistant", "de.r80.Assistant1"


class Assistant(QObject):
    """QML singleton mirroring hu-assistd (de.r80.Assistant1): ready (the speech engines are
    loaded), enabled (the setting), mode (idle | command | conversation), state (idle | greeting |
    listening | thinking | speaking), heard (what the driver said last), answer, turns, notice (why
    the last start was refused or the session stopped), engines, timing; command / conversation /
    stop go to assistd (the buttons VOICE and TALK reach it directly)."""
    changed = Signal()
    availableChanged = Signal()

    KEYS = {"Available": "ready", "Enabled": "enabled", "Mode": "mode", "State": "state", "Heard": "heard",
            "Answer": "answer", "Turns": "turns", "Notice": "notice", "Engines": "engines", "Timing": "timing"}

    def __init__(self, system_bus=False, parent=None):
        super().__init__(parent)
        self._available = False
        self._v = {"ready": False, "enabled": True, "mode": "idle", "state": "idle", "heard": "", "answer": "",
                   "turns": 0, "notice": "", "engines": {}, "timing": {}}
        DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus() if system_bus else dbus.SessionBus()
        self.bus.add_signal_receiver(self._on_props, "PropertiesChanged", PROPS, None, AST_PATH)
        self._poll = QTimer(self, interval=3000, timeout=self.refresh)
        self._poll.start()
        QTimer.singleShot(0, self.refresh)

    def refresh(self):
        self.bus.call_async(AST_SERVICE, AST_PATH, PROPS, "GetAll", "s", (AST_IFACE,),
                            self._apply, self._on_gone, timeout=1.0)

    def _on_gone(self, _err):
        if self._available:
            self._available = False
            self._v.update(mode="idle", state="idle")
            self.availableChanged.emit()
            self.changed.emit()

    def _on_props(self, iface, changed, _invalidated):
        if iface == AST_IFACE:
            self._apply(changed)

    def _apply(self, changed: dict):
        for k, v in changed.items():
            if str(k) in self.KEYS:
                self._v[self.KEYS[str(k)]] = _py(v)
        if not self._available:
            self._available = True
            self.availableChanged.emit()
        self.changed.emit()

    available = Property(bool, lambda self: self._available, notify=availableChanged)
    ready = Property(bool, lambda self: self._v["ready"], notify=changed)
    enabled = Property(bool, lambda self: self._v["enabled"], notify=changed)
    mode = Property(str, lambda self: self._v["mode"], notify=changed)
    state = Property(str, lambda self: self._v["state"], notify=changed)
    heard = Property(str, lambda self: self._v["heard"], notify=changed)
    answer = Property(str, lambda self: self._v["answer"], notify=changed)
    turns = Property(int, lambda self: self._v["turns"], notify=changed)
    notice = Property(str, lambda self: self._v["notice"], notify=changed)
    engines = Property("QVariantMap", lambda self: dict(self._v["engines"]), notify=changed)
    timing = Property("QVariantMap", lambda self: dict(self._v["timing"]), notify=changed)

    def _call(self, method):
        self.bus.call_async(AST_SERVICE, AST_PATH, AST_IFACE, method, "", (),
                            lambda *_: None, lambda e: log.warning(f"assistant {method}: {e}"), timeout=1.0)

    @Slot()
    def command(self):
        self._call("Command")

    @Slot()
    def conversation(self):
        self._call("Conversation")

    @Slot()
    def stop(self):
        self._call("Stop")
