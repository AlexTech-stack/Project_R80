import QtQuick
import QtQuick.Shapes

// FM tuner: station list on the left, analogue-style dial on the right.
Item {
    id: root
    function knob(d) { Sim.seek(d) }
    function side(d) { Sim.tune(d * 0.1) }
    function press() { Sim.band = Sim.band === "FM" ? "DAB+" : "FM" }

    // station list
    ListView {
        id: list
        x: Theme.margin
        y: 20
        width: 360
        height: parent.height - 40
        clip: true
        spacing: 6
        model: Sim.stations
        interactive: false
        delegate: MenuRow {
            width: list.width
            height: 62
            label: modelData.name
            value: modelData.freq.toFixed(1)
            selected: Math.abs(modelData.freq - Sim.frequency) < 0.05
            onClicked: Sim.frequency = modelData.freq
        }
    }
    Rectangle { x: list.x + list.width + 24; y: 30; width: 1; height: parent.height - 60; color: Theme.accentDim }

    Item {
        id: tuner
        x: list.x + list.width + 64
        y: 20
        width: parent.width - x - Theme.margin
        height: parent.height - 40

        // band + frequency
        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            y: 20
            spacing: 26
            T { text: Sim.band; font.pixelSize: 36; anchors.baseline: freq.baseline; color: Theme.accentMid }
            T { id: freq; text: Sim.frequency.toFixed(1); font.family: Theme.numberFamily; font.pixelSize: 120 }
            T { text: "MHz"; font.pixelSize: 30; anchors.baseline: freq.baseline; color: Theme.accentMid }
        }
        T {
            anchors.horizontalCenter: parent.horizontalCenter
            y: 170
            text: Sim.station ? Sim.station.name : "No station"
            font.pixelSize: Theme.fontLarge
        }

        // curved dial 87.5 .. 108 MHz
        Item {
            id: dial
            y: 250
            width: parent.width
            height: 150
            readonly property real r: 1400
            function xFor(f) { return 30 + (f - 87.5) / (108 - 87.5) * (width - 60) }
            function yFor(x) { const dx = x - width / 2; return 40 + (r - Math.sqrt(r * r - dx * dx)) }

            Repeater {
                model: 206   // 0.1 MHz steps
                Rectangle {
                    readonly property real f: 87.5 + index * 0.1
                    readonly property bool major: Math.abs(f - Math.round(f)) < 0.01 && Math.round(f) % 2 === 0
                    readonly property bool mid: Math.abs(f - Math.round(f)) < 0.01
                    visible: index % 5 === 0 || major
                    x: dial.xFor(f) - width / 2
                    y: dial.yFor(x)
                    width: 2
                    height: major ? 30 : mid ? 20 : 11
                    color: major ? Theme.accent : Theme.accentMid
                    rotation: (x - dial.width / 2) / dial.r * 57.3
                    transformOrigin: Item.Top
                }
            }
            Repeater {
                model: [88, 92, 96, 100, 104, 108]
                T {
                    x: dial.xFor(modelData) - width / 2
                    y: dial.yFor(x) + 38
                    text: modelData
                    font.pixelSize: Theme.fontSmall
                    color: Theme.accentMid
                }
            }
            // station markers
            Repeater {
                model: Sim.stations
                Rectangle {
                    x: dial.xFor(modelData.freq) - 3
                    y: dial.yFor(x) - 14
                    width: 6; height: 6; radius: 3
                    color: Theme.accentMid
                }
            }
            // needle
            Shape {
                id: needle
                x: dial.xFor(Sim.frequency) - 12
                y: dial.yFor(x + 12) - 30
                width: 24; height: 110
                Behavior on x { NumberAnimation { duration: 250; easing.type: Easing.OutCubic } }
                ShapePath {
                    strokeColor: Theme.accent; strokeWidth: 3; fillColor: Theme.accent
                    PathSvg { path: "M2 0 H22 L12 14 Z M12 14 V100" }
                }
            }
            MouseArea {
                anchors.fill: parent
                function set(mx) { Sim.frequency = Math.round(Math.min(108, Math.max(87.5, 87.5 + (mx - 30) / (dial.width - 60) * 20.5)) * 10) / 10 }
                onPressed: (m) => set(m.x)
                onPositionChanged: (m) => set(m.x)
            }
        }

        // RDS text + controls
        Rectangle {
            id: rdsBox
            y: 420
            width: parent.width; height: 56
            color: "transparent"
            border.color: Theme.accentDim
            clip: true
            T {
                id: rds
                y: 0; height: parent.height
                text: Sim.station ? Sim.station.rds : "Searching ..."
                font.family: Theme.monoFamily
                font.pixelSize: Theme.fontSmall + 1
                color: Theme.accentMid
                NumberAnimation on x {
                    from: rdsBox.width; to: -rds.implicitWidth
                    duration: 12000; loops: Animation.Infinite
                }
            }
        }
        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom
            spacing: 30
            LineButton { icon: Icons.prev; label: "Seek"; iconSize: 24; onClicked: Sim.seek(-1) }
            LineButton { icon: Icons.minus; iconSize: 24; onClicked: Sim.tune(-0.1) }
            LineButton { icon: Icons.plus; iconSize: 24; onClicked: Sim.tune(0.1) }
            LineButton { icon: Icons.next; label: "Seek"; iconSize: 24; onClicked: Sim.seek(1) }
            LineButton { icon: Icons.radio; label: Sim.band; iconSize: 26; onClicked: root.press() }
        }
    }
}
