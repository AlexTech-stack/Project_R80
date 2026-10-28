pragma Singleton
import QtQuick

// Demo stand-in for the Assistant backend (hu/ui/backend.py): same names, nothing connected,
// so Sim.qml uses its demo values. Loaded only in demo mode (hu/ui/run.py --demo,
// screenshots, Qt Design Studio); the live UI registers the real backend instead.
QtObject {
    property bool available: false
    property bool ready: false
    property bool enabled: true
    property string mode: "idle"
    property string state: "idle"
    property string heard: ""
    property string answer: ""
    property int turns: 0
    property string notice: ""
    property var engines: ({})
    property var timing: ({})
    signal changed()
    function command() {}
    function conversation() {}
    function stop() {}
}
