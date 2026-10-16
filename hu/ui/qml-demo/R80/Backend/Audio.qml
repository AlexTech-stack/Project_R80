pragma Singleton
import QtQuick

// Demo stand-in for the Audio backend (hu/ui/backend.py): same names, nothing connected,
// so Sim.qml uses its demo values. Loaded only in demo mode (hu/ui/run.py --demo,
// screenshots, Qt Design Studio); the live UI registers the real backend instead.
QtObject {
    property bool available: false
    property int master: 0
    property bool muted: false
    property int max: 30
    property var volumes: ({})
    property var tone: ({})
    signal changed()
    function setTone(name, value) {}
    function setMaster(value) {}
    function setMuted(muted) {}
    function setVolume(source, value) {}
    function setCallState(state) {}
}
