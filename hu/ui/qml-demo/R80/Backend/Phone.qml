pragma Singleton
import QtQuick

// Demo stand-in for the Phone backend (hu/ui/backend.py): same names, nothing connected,
// so Sim.qml uses its simulated phone. Loaded only in demo mode (hu/ui/run.py --demo,
// screenshots, Qt Design Studio); the live UI registers the real backend instead.
QtObject {
    property bool available: false
    property bool connected: false
    property string deviceName: ""
    property int battery: -1
    property string callState: "idle"
    property string callerName: ""
    property string callerNumber: ""
    property real callSince: 0
    signal changed()
    function dial(number) {}
    function answer() {}
    function hangup() {}
    function sendTones(tones) {}
}
