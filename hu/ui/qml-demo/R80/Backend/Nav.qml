pragma Singleton
import QtQuick

// Demo stand-in for the Nav backend (hu/ui/backend.py): same names, nothing connected,
// so Sim.qml uses its demo values. Loaded only in demo mode (hu/ui/run.py --demo,
// screenshots, Qt Design Studio); the live UI registers the real backend instead.
QtObject {
    property bool available: false
    property var phone: ({})
    property var guidance: ({})
    signal changed()
}
