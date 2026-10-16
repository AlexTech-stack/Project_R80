pragma Singleton
import QtQuick

// Demo stand-in for the System backend (hu/ui/backend.py): same names, nothing connected,
// so Sim.qml uses its demo values. Loaded only in demo mode (hu/ui/run.py --demo,
// screenshots, Qt Design Studio); the live UI registers the real backend instead.
QtObject {
    property bool available: false
    property var settings: ({})
    property real displayBrightness: 0.9
    property var info: ({})
    signal changed()
    function set(name, value) {}
    function resetAll() {}
}
