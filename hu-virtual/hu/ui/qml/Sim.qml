pragma Singleton
import QtQuick
import R80.Backend 1.0

// hu-virtual overlay of the mockup's Sim.qml. Same property names as the
// mockup; the vehicle values come from hu-vehicled over D-Bus (the Vehicle
// singleton) whenever the MCU link is up, and the media values from hu-mediad
// (the Media singleton), each falling back to the mockup's fake data when the
// matching service is not there. Radio / phone / nav are still simulated.
QtObject {
    id: sim

    readonly property bool live: Vehicle.linkUp
    property Connections vehicleConn: Connections {
        target: Vehicle
        function onValuesChanged() { sim._syncTrip() }
        function onVolumeStep(d) { sim.volume = Math.min(30, Math.max(0, sim.volume + d)) }
        function onMuteToggled() { if (sim.volume > 0) { sim._unmuteVolume = sim.volume; sim.volume = 0 } else sim.volume = sim._unmuteVolume }
        function onDimChanged() { Theme.brightness = Math.max(0.2, Vehicle.dimLevel / 100) }
    }

    signal navigate(string screen)

    // ---- time ------------------------------------------------------------
    property date now: new Date()
    property bool clock24h: true
    readonly property string timeText: Qt.formatTime(now, clock24h ? "HH:mm" : "h:mm AP")
    readonly property string dateText: now.toLocaleDateString(Qt.locale("de_DE"), "ddd, d. MMM yyyy")

    // ---- vehicle ---------------------------------------------------------
    // _-prefixed values are the mockup's own simulation, used when not live
    property real _speed: 0
    property real targetSpeed: 50
    property real _oilTemp: 92
    property real _batteryVolt: 14.2
    property real _fuelLevel: 0.62
    property real _odometer: 187432.4

    readonly property real speed: live ? Vehicle.speed : _speed
    readonly property real rpm: live ? Vehicle.rpm : (speed < 1 ? 780 : 900 + (speed % 45) * 48 + speed * 6)
    readonly property string gear: live ? Vehicle.gear : "D"
    readonly property real outsideTemp: live ? Vehicle.outsideTemp : 12
    readonly property real oilTemp: live ? Vehicle.oilTemp : _oilTemp
    readonly property real coolantTemp: live ? Vehicle.coolantTemp : 88
    readonly property real batteryVolt: live ? Vehicle.batteryVolt : _batteryVolt
    readonly property real fuelLevel: live ? Vehicle.fuelLevel : _fuelLevel          // 0..1
    readonly property int rangeKm: live ? Vehicle.rangeKm : Math.round(fuelLevel * 760)
    readonly property real odometer: live ? Vehicle.odometer : _odometer
    // writable: the Vehicle screen resets it. Live, a reset keeps an offset
    // against the car's trip counter (the real HU would ask the cluster instead).
    property real tripKm: 43.7
    property real _tripBase: 0
    property bool _tripSync: false
    onTripKmChanged: if (live && !_tripSync) _tripBase = Vehicle.tripKm - tripKm
    function _syncTrip() { if (!live) return; _tripSync = true; tripKm = Vehicle.tripKm - _tripBase; _tripSync = false }
    property int tripMinutes: 52
    readonly property real avgConsumption: live ? Vehicle.avgConsumption : 11.8
    readonly property int avgSpeed: Math.round(tripKm / Math.max(tripMinutes, 1) * 60)
    readonly property var tyres: live ? Vehicle.tyres : [2.3, 2.3, 2.2, 2.2]   // FL FR RL RR, bar
    readonly property int serviceKm: live ? Vehicle.serviceKm : 6400
    readonly property int serviceDays: live ? Vehicle.serviceDays : 112
    property int altitude: 412
    property int volume: 14
    property int _unmuteVolume: 14
    property int homeIndex: 0
    property bool units_metric: true

    // ---- media -----------------------------------------------------------
    // hu-mediad (de.r80.Media1, singleton Media) drives these when it runs;
    // otherwise the mockup's own playlist below keeps the screen alive.
    property var _tracks: [
        { title: "The Passenger",    artist: "Iggy Pop",          album: "Lust for Life",      duration: 296 },
        { title: "Night Drive",      artist: "Neon Autobahn",     album: "Kilometer Null",     duration: 241 },
        { title: "Red Horizon",      artist: "The Quattro Lines", album: "V8 Sessions",        duration: 318 },
        { title: "Tunnel Vision",    artist: "Lumen Drift",       album: "After Hours",        duration: 205 },
        { title: "Coastline",        artist: "Marta Kovac",       album: "Blue Roads",         duration: 263 },
        { title: "Low Frequencies",  artist: "Nord Signal",       album: "Carrier Wave",       duration: 227 }
    ]
    readonly property bool mediaLive: Media.available && Media.trackCount > 0
    property bool _mediaSync: false

    property int trackIndex: 0
    property int trackPos: 137
    property bool playing: true
    property bool shuffle: false
    property bool repeatAll: true
    property string mediaSource: "USB"

    readonly property var tracks: mediaLive ? Media.tracks : _tracks
    readonly property var track: tracks.length ? tracks[Math.min(trackIndex, tracks.length - 1)] : null

    function _pullMedia() {
        if (!mediaLive) return
        _mediaSync = true
        playing = Media.playing
        trackIndex = Media.trackIndex
        trackPos = Media.trackPos
        shuffle = Media.shuffle
        repeatAll = Media.repeatAll
        mediaSource = Media.mediaSource
        _mediaSync = false
    }
    onPlayingChanged: if (mediaLive && !_mediaSync) Media.setPlaying(playing)
    onTrackIndexChanged: if (mediaLive && !_mediaSync) Media.setTrack(trackIndex)
    onTrackPosChanged: if (mediaLive && !_mediaSync) Media.setPosition(trackPos)
    onShuffleChanged: if (mediaLive && !_mediaSync) Media.setShuffle(shuffle)
    onRepeatAllChanged: if (mediaLive && !_mediaSync) Media.setRepeatAll(repeatAll)
    onMediaSourceChanged: if (mediaLive && !_mediaSync) Media.setSource(mediaSource)

    property Connections mediaConn: Connections {
        target: Media
        function onChanged() { sim._pullMedia() }
        function onAvailableChanged() { sim._pullMedia() }
    }

    function nextTrack() {
        if (mediaLive) { Media.next(); return }
        trackIndex = (trackIndex + 1) % _tracks.length; trackPos = 0
    }
    function prevTrack() {
        if (mediaLive) { Media.prev(); return }
        if (trackPos > 3) { trackPos = 0; return }
        trackIndex = (trackIndex - 1 + _tracks.length) % _tracks.length; trackPos = 0
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

    // ---- navigation --------------------------------------------------------
    // Route in map coordinates (map is 2000 x 2000 units). One unit ~ 3.4 m.
    readonly property var routePoints: [
        [1000, 1960], [1000, 1560], [1180, 1380], [1560, 1380], [1560, 980],
        [1300, 720], [880, 720], [880, 420], [1080, 220], [1080, 60]
    ]
    readonly property var routeStreets: [
        "Hauptstraße", "Ringstraße", "Bergstraße", "Parkallee", "Uferweg",
        "Lindenstraße", "Marktplatz", "Schlossweg", "Am Ziel"
    ]
    readonly property string destination: "Schlossweg 8, Altstadt"
    readonly property real routeKm: 8.4
    readonly property var routeLengths: {
        const out = [0];
        for (let i = 1; i < routePoints.length; i++) {
            const dx = routePoints[i][0] - routePoints[i - 1][0], dy = routePoints[i][1] - routePoints[i - 1][1];
            out.push(out[i - 1] + Math.sqrt(dx * dx + dy * dy));
        }
        return out;
    }
    readonly property string routePath: {
        // polyline with softly rounded corners
        const p = routePoints; const r = 60;
        let s = "M" + p[0][0] + " " + p[0][1];
        for (let i = 1; i < p.length - 1; i++) {
            const a = p[i - 1], b = p[i], c = p[i + 1];
            const l1 = Math.hypot(b[0] - a[0], b[1] - a[1]), l2 = Math.hypot(c[0] - b[0], c[1] - b[1]);
            const k1 = Math.min(r, l1 / 2) / l1, k2 = Math.min(r, l2 / 2) / l2;
            s += " L" + (b[0] - (b[0] - a[0]) * k1).toFixed(1) + " " + (b[1] - (b[1] - a[1]) * k1).toFixed(1);
            s += " Q" + b[0] + " " + b[1] + " " + (b[0] + (c[0] - b[0]) * k2).toFixed(1) + " " + (b[1] + (c[1] - b[1]) * k2).toFixed(1);
        }
        return s + " L" + p[p.length - 1][0] + " " + p[p.length - 1][1];
    }
    property real navProgress: 0.08
    property bool navGuidance: true
    property bool headingUp: true
    property real mapZoom: 1.0

    readonly property var nextManeuver: {
        const total = routeLengths[routeLengths.length - 1];
        const pos = navProgress * total;
        for (let i = 1; i < routePoints.length - 1; i++) {
            if (routeLengths[i] > pos) {
                const a = routePoints[i - 1], b = routePoints[i], c = routePoints[i + 1];
                const v1x = b[0] - a[0], v1y = b[1] - a[1], v2x = c[0] - b[0], v2y = c[1] - b[1];
                const cross = v1x * v2y - v1y * v2x;
                const ang = Math.abs(Math.atan2(cross, v1x * v2x + v1y * v2y)) * 180 / Math.PI;
                const type = ang < 20 ? "straight" : (cross > 0 ? "right" : "left");
                return { type: type, street: routeStreets[i], km: (routeLengths[i] - pos) / total * routeKm };
            }
        }
        return { type: "flag", street: destination, km: (total - pos) / total * routeKm };
    }
    readonly property string currentStreet: {
        const total = routeLengths[routeLengths.length - 1];
        for (let i = 1; i < routeLengths.length; i++)
            if (routeLengths[i] > navProgress * total) return routeStreets[i - 1];
        return routeStreets[routeStreets.length - 1];
    }
    readonly property real remainingKm: (1 - navProgress) * routeKm
    readonly property int remainingMin: Math.max(1, Math.round(remainingKm / 40 * 60))
    readonly property date eta: new Date(now.getTime() + remainingMin * 60000)

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
            if (sim.playing && !sim.mediaLive) {
                sim.trackPos += 1;
                if (sim.trackPos >= sim.track.duration) sim.nextTrack();
            }
            if (sim.callState === "active") sim.callSeconds += 1;
            if (!sim.live) {
                sim._odometer += sim.speed / 3600;
                sim.tripKm += sim.speed / 3600;
                sim._fuelLevel = Math.max(0.05, sim._fuelLevel - sim.speed * 0.0000004);
                sim._batteryVolt = 14.1 + Math.random() * 0.2;
                sim._oilTemp = Math.round(91 + Math.random() * 2);
            }
            if (Math.random() < 0.02) sim.tripMinutes += 1;
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
            sim._speed += (sim.targetSpeed - sim._speed) * 0.02;
            if (sim._speed < 0.3 && sim.targetSpeed === 0) sim._speed = 0;
            if (sim.navGuidance) {
                sim.navProgress += 0.00006 + sim.speed * 0.0000012;
                if (sim.navProgress > 1) sim.navProgress = 0;
            }
        }
    }
}
