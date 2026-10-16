import QtQuick

// Thin line slider with a filled part and a round knob, like the vision sheet.
Item {
    id: root
    property real from: 0
    property real to: 1
    property real value: 0.5
    property bool centered: false   // fill from the middle (balance, bass, ...)
    property bool focused: false
    signal moved(real v)
    implicitWidth: 360
    implicitHeight: 40
    readonly property real frac: (value - from) / (to - from)

    Rectangle {
        id: track
        anchors.verticalCenter: parent.verticalCenter
        width: parent.width; height: 10; radius: 5
        color: "transparent"
        border.color: root.focused ? Theme.accent : Theme.accentDim
        border.width: 2
    }
    Rectangle {
        anchors.verticalCenter: parent.verticalCenter
        x: root.centered ? Math.min(track.width / 2, root.frac * track.width) : 0
        width: root.centered ? Math.abs(root.frac - 0.5) * track.width : root.frac * track.width
        height: 10; radius: 5
        color: Theme.accent
    }
    Rectangle {
        width: 22; height: 22; radius: 11
        anchors.verticalCenter: parent.verticalCenter
        x: root.frac * track.width - width / 2
        color: Theme.bg
        border.color: Theme.accent
        border.width: 3
    }
    MouseArea {
        anchors.fill: parent
        anchors.margins: -10
        function update(mx) {
            const f = Math.min(1, Math.max(0, (mx - 10) / track.width));
            root.moved(root.from + f * (root.to - root.from));
        }
        onPressed: (m) => update(m.x)
        onPositionChanged: (m) => update(m.x)
    }
}
