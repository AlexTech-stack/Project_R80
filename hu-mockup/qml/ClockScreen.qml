import QtQuick

// Big clock, date, weather and altitude.
Item {
    id: root
    function knob(d) {}
    function press() { Sim.clock24h = !Sim.clock24h }

    Rectangle {
        x: Theme.margin; y: 24
        width: parent.width - 2 * Theme.margin
        height: parent.height - 48
        color: "transparent"
        border.color: Theme.accent; border.width: 2
        radius: 8

        Column {
            x: 70
            anchors.verticalCenter: parent.verticalCenter
            anchors.verticalCenterOffset: -30
            spacing: 6
            T {
                text: Qt.formatTime(Sim.now, Sim.clock24h ? "HH:mm" : "h:mm")
                font.family: Theme.numberFamily
                font.pixelSize: 250
                font.letterSpacing: 6
            }
            T {
                text: Qt.formatTime(Sim.now, "ss") + " s"
                color: Theme.accentDim
                font.family: Theme.monoFamily
                font.pixelSize: Theme.fontNormal
                x: 8
            }
            T { x: 8; text: Sim.dateText; font.pixelSize: 38 }
        }

        Rectangle { x: 780; y: 30; width: 2; height: parent.height - 60; color: Theme.accent }

        Column {
            x: 830
            y: 40
            spacing: 18
            Row {
                spacing: 20
                Icon { path: Icons.partCloud; width: 90; height: 90; stroke: 1.3 }
                Column {
                    anchors.verticalCenter: parent.verticalCenter
                    T { text: Math.round(Sim.outsideTemp) + " °C"; font.family: Theme.numberFamily; font.pixelSize: 64 }
                    T { text: "Partly cloudy"; color: Theme.accentMid; font.pixelSize: Theme.fontSmall }
                }
            }
            Rectangle { width: 340; height: 1; color: Theme.accentDim }
            Row {
                spacing: 20
                Icon { path: Icons.mountain; width: 60; height: 60 }
                Column {
                    anchors.verticalCenter: parent.verticalCenter
                    T { text: Sim.altitude + " m"; font.pixelSize: 40 }
                    T { text: "Altitude"; color: Theme.accentMid; font.pixelSize: Theme.fontSmall }
                }
            }
            Rectangle { width: 340; height: 1; color: Theme.accentDim }
            Row {
                spacing: 18
                Repeater {
                    model: Sim.forecast
                    Column {
                        width: 70
                        spacing: 4
                        T { anchors.horizontalCenter: parent.horizontalCenter; text: modelData.day; font.pixelSize: Theme.fontSmall; color: Theme.accentMid }
                        Icon { anchors.horizontalCenter: parent.horizontalCenter; path: Icons[modelData.icon]; width: 40; height: 40 }
                        T { anchors.horizontalCenter: parent.horizontalCenter; text: modelData.hi + "°"; font.pixelSize: Theme.fontNormal }
                        T { anchors.horizontalCenter: parent.horizontalCenter; text: modelData.lo + "°"; font.pixelSize: Theme.fontSmall; color: Theme.accentMid }
                    }
                }
            }
        }

        // bottom emblem sitting in the frame line
        Rectangle {
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.verticalCenter: parent.bottom
            width: 150; height: 40
            color: Theme.bg
            Logo { anchors.centerIn: parent }
        }
    }
}
