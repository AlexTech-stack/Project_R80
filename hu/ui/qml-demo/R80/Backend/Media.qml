pragma Singleton
import QtQuick

// Demo stand-in for the Media backend (hu/ui/backend.py): same names, nothing connected,
// so Sim.qml uses its demo values. Loaded only in demo mode (hu/ui/run.py --demo,
// screenshots, Qt Design Studio); the live UI registers the real backend instead.
QtObject {
    property bool available: false
    property var track: ({})
    property var upNext: []
    property string queueTitle: ""
    property string queue: ""
    property int sourceTrackCount: 0
    property int scanned: 0
    property bool playing: false
    property int trackIndex: 0
    property int trackPos: 0
    property bool shuffle: false
    property bool repeatAll: false
    property string mediaSource: ""
    property int trackCount: 0
    property var sources: []
    signal changed()
    signal browsed(string path, int offset, string title, int total, var entries)
    function playPause() {}
    function setPlaying(on) {}
    function next() {}
    function prev() {}
    function setTrack(index) {}
    function setPosition(s) {}
    function setShuffle(on) {}
    function setRepeatAll(on) {}
    function setSource(name) {}
    function browse(path, offset, count) {}
    function playFrom(path, index) {}
}
