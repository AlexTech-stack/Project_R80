import QtQuick
import QtQuick.Window

// R80 headunit UI mockup.
// Controls: mouse/touch, mouse wheel = MMI knob,
// Up/Down = turn knob, Left/Right = push knob sideways, Enter = press,
// Esc/Backspace = back to home, 1-8 = jump to screen, C = simulate incoming call,
// F11 = fullscreen.
Window {
    id: win
    width: Theme.screenWidth
    height: Theme.screenHeight
    visible: true
    color: "black"
    title: "R80 Headunit - UI mockup"

    property string current: "home"
    readonly property var screens: ({
        home:       { title: "",                file: "HomeScreen.qml" },
        navigation: { title: "Navigation",      file: "NavigationScreen.qml" },
        media:      { title: "Media",           file: "MediaScreen.qml" },
        radio:      { title: "Radio",           file: "RadioScreen.qml" },
        phone:      { title: "Phone",           file: "PhoneScreen.qml" },
        vehicle:    { title: "Vehicle",         file: "VehicleScreen.qml" },
        cluster:    { title: "Drive",           file: "ClusterScreen.qml" },
        clock:      { title: "Clock & Weather", file: "ClockScreen.qml" },
        settings:   { title: "Settings",        file: "SettingsScreen.qml" }
    })
    readonly property var order: ["navigation", "media", "radio", "phone", "vehicle", "cluster", "clock", "settings"]

    // set from run.py --screenshots to show the incoming-call overlay
    property bool demoCall: false
    onDemoCallChanged: if (demoCall) Sim.simulateIncomingCall()

    function go(name) { if (screens[name]) current = name }

    Connections {
        target: Sim
        function onNavigate(screen) { win.go(screen) }
    }

    Item {
        id: display
        width: Theme.screenWidth
        height: Theme.screenHeight
        anchors.centerIn: parent
        scale: Math.min(win.width / width, win.height / height)
        clip: true
        focus: true

        function target() { return Sim.callState !== "idle" ? callOverlay : loader.item }
        function knob(d) { const t = target(); if (t && t.knob) t.knob(d) }
        function side(d) { const t = target(); if (t && t.side) t.side(d); else knob(d) }
        function press() { const t = target(); if (t && t.press) t.press() }

        Keys.onPressed: (e) => {
            switch (e.key) {
            case Qt.Key_Up: knob(-1); break;
            case Qt.Key_Down: knob(1); break;
            case Qt.Key_Left: side(-1); break;
            case Qt.Key_Right: side(1); break;
            case Qt.Key_Return: case Qt.Key_Enter: case Qt.Key_Space: press(); break;
            case Qt.Key_Escape: case Qt.Key_Backspace: case Qt.Key_H:
                if (Sim.callState === "incoming") Sim.hangUp(); else win.go("home"); break;
            case Qt.Key_C: Sim.simulateIncomingCall(); break;
            case Qt.Key_F11: win.visibility = win.visibility === Window.FullScreen ? Window.Windowed : Window.FullScreen; break;
            default:
                if (e.key >= Qt.Key_1 && e.key <= Qt.Key_8) win.go(win.order[e.key - Qt.Key_1]);
                else return;
            }
            e.accepted = true;
        }

        Rectangle { anchors.fill: parent; color: Theme.bg }

        Header {
            id: header
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.right: parent.right
            title: win.screens[win.current].title
            onBack: win.go("home")
        }

        MouseArea {
            id: wheelArea
            anchors.top: header.bottom
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            acceptedButtons: Qt.NoButton
            property real acc: 0
            onWheel: (w) => {
                acc += w.angleDelta.y;
                while (acc >= 120) { display.knob(-1); acc -= 120 }
                while (acc <= -120) { display.knob(1); acc += 120 }
            }
            Loader {
                id: loader
                anchors.fill: parent
                source: win.screens[win.current].file
                onLoaded: fadeIn.restart()
                NumberAnimation { id: fadeIn; target: loader.item; property: "opacity"; from: 0; to: 1; duration: 220; easing.type: Easing.OutCubic }
            }
        }

        CallOverlay { id: callOverlay; anchors.fill: parent }

        // brightness
        Rectangle {
            anchors.fill: parent
            color: "black"
            opacity: (1 - Theme.brightness) * 0.85
        }
    }
}
