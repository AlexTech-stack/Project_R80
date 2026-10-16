pragma Singleton
import QtQuick

// Demo stand-in for the Vehicle backend (hu/ui/backend.py): same names, nothing connected,
// so Sim.qml uses its demo values. Loaded only in demo mode (hu/ui/run.py --demo,
// screenshots, Qt Design Studio); the live UI registers the real backend instead.
QtObject {
    property real speed: 0
    property real rpm: 0
    property string gear: ""
    property real outsideTemp: 0
    property real oilTemp: 0
    property real coolantTemp: 0
    property real batteryVolt: 0
    property real fuelLevel: 0
    property int rangeKm: 0
    property real odometer: 0
    property real tripKm: 0
    property real avgConsumption: 0
    property int serviceKm: 0
    property int serviceDays: 0
    property real boost: 0
    property real oilPressure: 0
    property string ignition: ""
    property string lights: ""
    property var tyres: []
    property var staleSignals: []
    property bool linkUp: false
    property string power: "on"
    property int dimLevel: 100
    property bool night: false
    signal valuesChanged()
    signal linkChanged()
    signal dimChanged()
    signal input(string kind, int value)
    signal volumeStep(int delta)
    signal muteToggled()
    function refresh() {}
}
