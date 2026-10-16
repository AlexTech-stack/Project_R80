pragma Singleton
import QtQuick

// Fake vehicle / media / phone / navigation data so the mockup feels alive.
// Nothing here talks to real hardware.
QtObject {
    id: sim

    signal navigate(string screen)

    // ---- time ------------------------------------------------------------
    property date now: new Date()
    property bool clock24h: true
    readonly property string timeText: Qt.formatTime(now, clock24h ? "HH:mm" : "h:mm AP")
    readonly property string dateText: now.toLocaleDateString(Qt.locale("de_DE"), "ddd, d. MMM yyyy")

    // ---- vehicle ---------------------------------------------------------
    property real speed: 0
    property real targetSpeed: 50
    readonly property real rpm: speed < 1 ? 780 : 900 + (speed % 45) * 48 + speed * 6
    property string gear: "D"
    property real outsideTemp: 12
    property real oilTemp: 92
    property real coolantTemp: 88
    property real batteryVolt: 14.2
    property real fuelLevel: 0.62          // 0..1
    readonly property int rangeKm: Math.round(fuelLevel * 760)
    property real odometer: 187432.4
    property real avgConsumption: 11.8
    // ---- trip computer (D10; from hu-tripd in hu-virtual) -------------------
    // {km, minutes, avgSpeed, maxSpeed}; "since start" and "long-term"
    property var tripStart: ({ km: 43.7, minutes: 52, avgSpeed: 50, maxSpeed: 128 })
    property var tripLong: ({ km: 1874.2, minutes: 1712, avgSpeed: 66, maxSpeed: 187 })
    function resetTrip(which) { _setTrip(which, { km: 0, minutes: 0, avgSpeed: 0, maxSpeed: 0 }) }
    function _setTrip(which, v) { if (which === "start") tripStart = v; else tripLong = v }
    property real _tripSeconds: 0
    function _driveTrips(dt) {                // the fake data's own trip computer
        _tripSeconds += dt
        for (const which of ["start", "long"]) {
            const t = which === "start" ? tripStart : tripLong
            const km = t.km + speed * dt / 3600
            const minutes = t.minutes + (_tripSeconds >= 60 ? 1 : 0)
            _setTrip(which, { km: km, minutes: minutes, avgSpeed: minutes ? Math.round(km / minutes * 60) : 0,
                              maxSpeed: Math.max(t.maxSpeed, Math.round(speed)) })
        }
        if (_tripSeconds >= 60) _tripSeconds = 0
    }
    property var tyres: [2.3, 2.3, 2.2, 2.2]   // FL FR RL RR, bar
    property int serviceKm: 6400
    property int serviceDays: 112
    property int altitude: 412
    // ---- audio (D9): master volume, mute, one volume per source ----------
    property int volume: 14                // master volume, 0 .. volumeMax
    property int volumeMax: 30
    property bool muted: false
    property int mediaVolume: 30
    property int navVolume: 30
    property int phoneVolume: 30
    property int radioVolume: 30
    property int chimeVolume: 30
    function toggleMute() { muted = !muted }

    // ---- warnings (D10; from hu-warnd in hu-virtual) ----------------------
    // Most urgent first: {id, severity: warning | information | notice, text, acknowledged, since (s)}
    property var warnings: []
    function acknowledgeWarning(id) {
        warnings = warnings.map(w => w.id === id ? Object.assign({}, w, { acknowledged: true }) : w)
    }
    function acknowledgeAllWarnings() { warnings = warnings.map(w => Object.assign({}, w, { acknowledged: true })) }
    function simulateWarnings() {
        warnings = [
            { id: "tyre_dropping.TyrePressureFL", severity: "warning", acknowledged: false, since: 3,
              text: "Tyre pressure dropping fast, front left (0.15 bar/s)" },
            { id: "fuel_low", severity: "information", acknowledged: false, since: 40, text: "Fuel low (8 %)" },
            { id: "service_distance", severity: "notice", acknowledged: false, since: 300, text: "Service due in 800 km" }
        ]
    }
    property int homeIndex: 0
    property bool units_metric: true

    // ---- media -----------------------------------------------------------
    property var tracks: [
        { title: "The Passenger",    artist: "Iggy Pop",          album: "Lust for Life",      duration: 296 },
        { title: "Night Drive",      artist: "Neon Autobahn",     album: "Kilometer Null",     duration: 241 },
        { title: "Red Horizon",      artist: "The Quattro Lines", album: "V8 Sessions",        duration: 318 },
        { title: "Tunnel Vision",    artist: "Lumen Drift",       album: "After Hours",        duration: 205 },
        { title: "Coastline",        artist: "Marta Kovac",       album: "Blue Roads",         duration: 263 },
        { title: "Low Frequencies",  artist: "Nord Signal",       album: "Carrier Wave",       duration: 227 }
    ]
    property int trackIndex: 0
    property int trackPos: 137
    property bool playing: true
    property bool shuffle: false
    property bool repeatAll: true
    property string mediaSource: "USB"
    readonly property var track: tracks[trackIndex]
    function nextTrack() { trackIndex = (trackIndex + 1) % tracks.length; trackPos = 0 }
    function prevTrack() {
        if (trackPos > 3) { trackPos = 0; return }
        trackIndex = (trackIndex - 1 + tracks.length) % tracks.length; trackPos = 0
    }
    function fmtTime(s) { s = Math.max(0, Math.floor(s)); return Math.floor(s / 60) + ":" + ("0" + (s % 60)).slice(-2) }

    // ---- radio -----------------------------------------------------------
    property string band: "FM"
    property real frequency: 93.6
    property var stations: [
        { freq: 89.1,  name: "Radio Polar",   rds: "Morning show with traffic every 20 minutes" },
        { freq: 90.5,  name: "Klassik Süd",   rds: "Now: Symphony No. 7, 2nd movement" },
        { freq: 93.6,  name: "City 93.6",     rds: "City 93.6  -  the best hits of the 80s, 90s and today" },
        { freq: 96.3,  name: "Jazzwelle",     rds: "Late Night Jazz  -  live from the Blue Room" },
        { freq: 99.9,  name: "Autobahn FM",   rds: "Traffic: A9 clear, A8 roadworks near Ulm" },
        { freq: 102.7, name: "Talk 102",      rds: "News at the top of the hour" },
        { freq: 105.2, name: "Rock Linie",    rds: "Classic rock, non-stop" }
    ]
    readonly property var station: {
        for (let i = 0; i < stations.length; i++)
            if (Math.abs(stations[i].freq - frequency) < 0.05) return stations[i];
        return null;
    }
    function tune(delta) { frequency = Math.round(Math.min(108, Math.max(87.5, frequency + delta)) * 10) / 10 }
    function seek(dir) {
        let best = null;
        for (let i = 0; i < stations.length; i++) {
            const f = stations[i].freq;
            if (dir > 0 && f > frequency + 0.05 && (best === null || f < best)) best = f;
            if (dir < 0 && f < frequency - 0.05 && (best === null || f > best)) best = f;
        }
        if (best === null) best = dir > 0 ? stations[0].freq : stations[stations.length - 1].freq;
        frequency = best;
    }

    // ---- phone -----------------------------------------------------------
    property string callState: "idle"      // idle | incoming | active
    property string caller: "Anna"
    property string callerNumber: "+49 171 2345 678"
    property int callSeconds: 0
    property bool micMuted: false
    property string phoneName: "Alex's phone"
    property int phoneBattery: 78
    property var contacts: [
        { name: "Anna",          number: "+49 171 2345 678", fav: true },
        { name: "Workshop Bernd",number: "+49 89 998 877",   fav: true },
        { name: "Home",          number: "+49 89 123 456",   fav: true },
        { name: "Chris",         number: "+49 160 555 0101", fav: false },
        { name: "Daniela",       number: "+49 152 777 4411", fav: false },
        { name: "Emergency ADAC",number: "+49 89 22 22 22",  fav: false },
        { name: "Felix",         number: "+49 176 111 2233", fav: false },
        { name: "Parts dealer",  number: "+49 711 404 040",  fav: false }
    ]
    property var recents: [
        { name: "Anna",           kind: "in",     when: "13:58" },
        { name: "Workshop Bernd", kind: "out",    when: "11:20" },
        { name: "+49 30 555 123", kind: "missed", when: "Yesterday" },
        { name: "Home",           kind: "out",    when: "Yesterday" },
        { name: "Chris",          kind: "in",     when: "Mon" }
    ]
    function numberFor(name) {
        for (let i = 0; i < contacts.length; i++) if (contacts[i].name === name) return contacts[i].number;
        return /^[+0-9*# ]+$/.test(name) ? "" : "Mobile";
    }
    function simulateIncomingCall(name) {
        caller = name || "Anna"; callerNumber = numberFor(caller);
        callSeconds = 0; micMuted = false; callState = "incoming";
    }
    function dial(name) { caller = name; callerNumber = numberFor(name); callSeconds = 0; micMuted = false; callState = "active" }
    function answer() { callSeconds = 0; callState = "active" }
    function hangUp() { callState = "idle" }

    // ---- settings (D12; names as in hu-virtual/hu/system.ini, kept by hu-sysd there) --------
    property string accent: "signal_red"
    property real brightness: 0.9
    property bool nightDimming: true
    // What the display shows. Here: the user's brightness (no car dimmer in the mockup).
    readonly property real displayBrightness: brightness
    function setSetting(name, value) {
        if (name === "accent") accent = value;
        else if (name === "brightness") brightness = value;
        else if (name === "night_dimming") nightDimming = value;
        else if (name === "clock_24h") clock24h = value;
        else if (name === "units") units_metric = value === "metric";
    }

    // ---- system information (Settings -> System; hu-sysd's Info in hu-virtual) ---------------
    readonly property date _bootTime: new Date(now.getTime() - 3 * 3600 * 1000 - 12 * 60 * 1000)
    readonly property var systemInfo: ({
        version: "mockup", os: "simulated", kernel: "-", host: "r80-mockup",
        uptime_s: Math.floor((now - _bootTime) / 1000), cpu_temp_c: 48.5, load: 0.42,
        mem_total_mb: 905, mem_available_mb: 512, disk_free_mb: 6900,
        services_up: ["de.r80.Vehicle", "de.r80.Media", "de.r80.Audio", "de.r80.Warnings", "de.r80.Trip",
                      "de.r80.Nav", "de.r80.System"],
        services_missing: [], bt_name: "R80", bt_address: "B8:27:EB:00:00:00", bt_powered: true
    })

    // ---- tone (D9: hu-audiod keeps it; applied once the DSP amplifier is chosen) ------------
    property int toneBass: 0
    property int toneTreble: 0
    property real toneBalance: 0
    property bool loudness: true
    function setTone(name, value) {
        if (name === "bass") toneBass = value;
        else if (name === "treble") toneTreble = value;
        else if (name === "balance") toneBalance = value;
        else if (name === "loudness") loudness = value;
    }

    // ---- navigation (D11: the phone navigates, the HU shows its guidance) ----
    // A fake phone drives a demo route: the same legs as hu-virtual/phone_emu/route_demo.json.
    readonly property var navRoute: [
        { m: 1400, maneuver: "turn", modifier: "right", street: "Ringstraße" },
        { m: 1300, maneuver: "turn", modifier: "slight_right", street: "Bergstraße" },
        { m: 1300, maneuver: "turn", modifier: "left", street: "Parkallee" },
        { m: 1250, maneuver: "roundabout", exit: 2, street: "Uferweg" },
        { m: 1400, maneuver: "turn", modifier: "left", street: "Lindenstraße" },
        { m: 1000, maneuver: "turn", modifier: "right", street: "Marktplatz" },
        { m: 700, maneuver: "fork", modifier: "slight_left", street: "Schlossweg" },
        { m: 550, maneuver: "arrive", street: "Schlossweg 8" }
    ]
    readonly property real _navTotal: navRoute.reduce((a, l) => a + l.m, 0)
    property real _navDriven: 1050
    // What the demo shows (key N cycles): "live", "stale" (phone link lost), "idle" (phone
    // connected, no route), "nophone", and edge cases the phone panel also sends: "reroute"
    // (status text, no arrow), "signpost" (long signpost text), "arrive" (destination on the left).
    property string navDemo: "live"
    readonly property var _navDemoNext: ({ live: "stale", stale: "idle", idle: "nophone", nophone: "reroute",
                                           reroute: "signpost", signpost: "arrive", arrive: "live" })
    function simulateNavState() { navDemo = _navDemoNext[navDemo] }
    readonly property var _navDemoCases: ({
        reroute: { maneuver: "unknown", modifier: "", distance: -1, street: "", text: "Route wird neu berechnet…",
                   remainingM: -1, remainingS: -1 },
        signpost: { maneuver: "turn", modifier: "right", distance: 80, text: "", remainingM: 7300, remainingS: 660,
                    street: "Pragstraße Richtung A8 A81 B10 B27 Karlsruhe / Heilbronn / Vaihingen/Enz / Ludwigsburg / S-Zentrum / S-Feuerbach" },
        arrive: { maneuver: "arrive", modifier: "left", distance: 40, street: "Schlossweg 8", text: "",
                  remainingM: 40, remainingS: 30 }
    })
    function _driveRoute(dt) {
        _navDriven += speed / 3.6 * dt;
        if (_navDriven >= _navTotal) _navDriven = 0;
    }
    readonly property var _noGuidance: ({ active: false, stale: false, source: "", maneuver: "", modifier: "", exit: 0,
                                          distance: -1, street: "", text: "", remainingM: -1, remainingS: -1, arrival: null })
    // Phone link: { connected, device }
    readonly property var navPhone: ({ connected: navDemo !== "stale" && navDemo !== "nophone", device: "Redmi Note 12 Pro 5G" })
    // Guidance: { active, stale, source, maneuver, modifier, exit, distance (m), street, text,
    //             remainingM, remainingS, arrival (Date) }; -1 / null = not known
    readonly property var guidance: {
        if (navDemo === "idle" || navDemo === "nophone") return _noGuidance;
        const c = _navDemoCases[navDemo];
        if (c) return { active: true, stale: false, source: "google_maps", maneuver: c.maneuver, modifier: c.modifier,
                        exit: 0, distance: c.distance, street: c.street, text: c.text, remainingM: c.remainingM,
                        remainingS: c.remainingS,
                        arrival: c.remainingS >= 0 ? new Date(now.getTime() + c.remainingS * 1000) : null };
        let at = 0, leg = navRoute[navRoute.length - 1];
        for (const l of navRoute) { at += l.m; if (at > _navDriven) { leg = l; break; } }
        const remaining = _navTotal - _navDriven, secs = remaining / (40 / 3.6);
        return { active: true, stale: navDemo === "stale", source: "google_maps", maneuver: leg.maneuver,
                 modifier: leg.modifier || "", exit: leg.exit || 0, distance: at - _navDriven, street: leg.street,
                 text: "", remainingM: remaining, remainingS: secs, arrival: new Date(now.getTime() + secs * 1000) };
    }

    // ---- weather -------------------------------------------------------------
    property var forecast: [
        { day: "Fr", icon: "partCloud", hi: 14, lo: 6 },
        { day: "Sa", icon: "sun",       hi: 17, lo: 7 },
        { day: "So", icon: "rain",      hi: 11, lo: 5 },
        { day: "Mo", icon: "cloud",     hi: 12, lo: 4 }
    ]

    // ---- ticking -------------------------------------------------------------
    property Timer secondTimer: Timer {
        interval: 1000; running: true; repeat: true
        onTriggered: {
            sim.now = new Date();
            if (sim.playing) {
                sim.trackPos += 1;
                if (sim.trackPos >= sim.track.duration) sim.nextTrack();
            }
            if (sim.callState === "active") sim.callSeconds += 1;
            sim.odometer += sim.speed / 3600;
            sim._driveTrips(1);
            sim.fuelLevel = Math.max(0.05, sim.fuelLevel - sim.speed * 0.0000004);
            sim.batteryVolt = 14.1 + Math.random() * 0.2;
            sim.oilTemp = Math.round(91 + Math.random() * 2);
        }
    }
    property Timer driveTimer: Timer {
        interval: 50; running: true; repeat: true
        property int t: 0
        onTriggered: {
            t += 1;
            if (t % 120 === 0) {
                const r = Math.random();
                sim.targetSpeed = r < 0.12 ? 0 : (r < 0.5 ? 30 + Math.random() * 30 : 60 + Math.random() * 80);
            }
            sim.speed += (sim.targetSpeed - sim.speed) * 0.02;
            if (sim.speed < 0.3 && sim.targetSpeed === 0) sim.speed = 0;
            if (sim.navDemo === "live") sim._driveRoute(0.05);
        }
    }
}
