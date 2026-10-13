import QtQuick

// Master volume popup (D9), opened from the VolumeBadge. Slider and mute button;
// the knob changes the volume while it is open, press or Back closes it, and it
// closes by itself a few seconds after the last change.
Item {
    id: root
    property bool open: false
    visible: open
    anchors.fill: parent

    function show() { open = true; idle.restart() }
    function close() { open = false }
    function setVolume(v) { Sim.volume = Math.min(Sim.volumeMax, Math.max(0, Math.round(v))); idle.restart() }
    function knob(d) { setVolume(Sim.volume - d) }      // knob up (-1) = louder
    function side(d) { setVolume(Sim.volume + d) }
    function press() { close() }

    Timer { id: idle; interval: 5000; onTriggered: root.close() }

    // a click anywhere else closes it
    MouseArea { anchors.fill: parent; onClicked: root.close() }
    Rectangle { anchors.fill: parent; color: Theme.shade; opacity: 0.45 }

    Rectangle {
        id: panel
        x: Theme.margin
        y: parent.height - height - 78
        width: 560; height: 190
        color: Theme.bg
        border.color: Theme.accent
        border.width: 2
        MouseArea { anchors.fill: parent }    // keep clicks on the panel from closing it

        Row {
            x: 28; y: 22
            spacing: 14
            Icon { path: Icons.speaker; width: 32; height: 32; anchors.verticalCenter: parent.verticalCenter }
            T { text: "Volume"; anchors.verticalCenter: parent.verticalCenter }
        }
        T {
            anchors.right: parent.right; anchors.rightMargin: 28; y: 10
            text: Sim.volume
            font.family: Theme.numberFamily
            font.pixelSize: 56
            color: Sim.muted ? Theme.accentDim : Theme.accent
        }
        LineSlider {
            x: 28; y: 96
            width: 330
            from: 0; to: Sim.volumeMax
            value: Sim.volume
            focused: true
            onMoved: (v) => root.setVolume(v)
        }
        LineButton {
            anchors.right: parent.right; anchors.rightMargin: 28
            y: 94
            icon: Sim.muted ? Icons.mute : Icons.speaker
            label: Sim.muted ? "Unmute" : "Mute"
            iconSize: 22
            highlighted: Sim.muted
            onClicked: { Sim.toggleMute(); idle.restart() }
        }
        T {
            x: 28; y: 146
            text: Sim.muted ? "Muted" : "Turn the knob to change, press to close"
            color: Theme.accentMid
            font.pixelSize: Theme.fontSmall
        }
    }
}
