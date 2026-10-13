import QtQuick

// Master volume in the bottom-left corner of every screen (D9).
// Click (or tap) opens the master volume popup.
Item {
    id: root
    signal clicked()
    width: row.width + 24
    height: 44

    // dark backing so it stays readable on top of the map
    Rectangle { anchors.fill: parent; radius: 3; color: Theme.bg; opacity: 0.8 }
    Row {
        id: row
        x: 12
        anchors.verticalCenter: parent.verticalCenter
        spacing: 10
        Icon {
            anchors.verticalCenter: parent.verticalCenter
            path: Sim.muted ? Icons.mute : Icons.speaker
            width: 26; height: 26
            color: Sim.muted ? Theme.accentDim : Theme.accentMid
        }
        T {
            anchors.verticalCenter: parent.verticalCenter
            text: Sim.muted ? "Muted" : Sim.volume
            color: Sim.muted ? Theme.accentDim : Theme.accentMid
            font.family: Sim.muted ? Theme.fontFamily : Theme.numberFamily
            font.pixelSize: Sim.muted ? Theme.fontSmall : Theme.fontNormal
        }
    }
    MouseArea { anchors.fill: parent; onClicked: root.clicked() }
}
