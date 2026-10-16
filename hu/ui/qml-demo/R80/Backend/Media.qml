pragma Singleton
import QtQuick

// Demo stand-in for the Media backend (hu/ui/backend.py): same names, nothing connected,
// so Sim.qml uses its demo values. Loaded only in demo mode (hu/ui/run.py --demo,
// screenshots, Qt Design Studio); the live UI registers the real backend instead.
QtObject {
    property bool available: false
    property var tracks: []
    property bool playing: false
    property int trackIndex: 0
    property int trackPos: 0
    property bool shuffle: false
    property bool repeatAll: false
    property string mediaSource: ""
    property int trackCount: 0
    property var sources: []
    signal changed()
    function playPause() {}
    function setPlaying(on) {}
    function next() {}
    function prev() {}
    function setTrack(index) {}
    function setPosition(s) {}
    function setShuffle(on) {}
    function setRepeatAll(on) {}
    function setSource(name) {}
}
