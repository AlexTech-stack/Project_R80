import QtQuick

// Incoming / active call popup, shown on top of any screen.
Item {
    id: root
    visible: Sim.callState !== "idle"
    property int sel: 0
    readonly property var actions: Sim.callState === "incoming" ? ["answer", "decline"] : ["mute", "end"]
    onVisibleChanged: sel = 0

    function knob(d) { sel = (sel + d + actions.length) % actions.length }
    function press() { run(actions[sel]) }
    function run(a) {
        if (a === "answer") Sim.answer();
        else if (a === "decline" || a === "end") Sim.hangUp();
        else if (a === "mute") Sim.micMuted = !Sim.micMuted;
        sel = 0;
    }

    Rectangle { anchors.fill: parent; color: "black"; opacity: 0.72 }
    MouseArea { anchors.fill: parent }  // modal

    Rectangle {
        id: box
        width: 760; height: 420
        anchors.centerIn: parent
        anchors.verticalCenterOffset: 30
        color: Theme.bg
        border.color: Theme.accent
        border.width: 2
        radius: 6

        Row {
            x: 60; y: 56
            spacing: 36
            Item {
                width: 110; height: 110
                Rectangle {
                    anchors.fill: parent; radius: width / 2
                    color: "transparent"; border.color: Theme.accent; border.width: 2
                }
                Icon { anchors.centerIn: parent; width: 56; height: 56; path: Icons.phone; stroke: 1.5 }
                // pulsing ring while ringing
                Rectangle {
                    id: pulse
                    anchors.centerIn: parent
                    width: parent.width; height: width; radius: width / 2
                    color: "transparent"; border.color: Theme.accent; border.width: 2
                    visible: Sim.callState === "incoming"
                    SequentialAnimation on scale {
                        running: pulse.visible; loops: Animation.Infinite
                        NumberAnimation { from: 1; to: 1.5; duration: 1100 }
                    }
                    SequentialAnimation on opacity {
                        running: pulse.visible; loops: Animation.Infinite
                        NumberAnimation { from: 0.8; to: 0; duration: 1100 }
                    }
                }
            }
            Column {
                anchors.verticalCenter: parent.verticalCenter
                spacing: 8
                T {
                    text: Sim.callState === "incoming" ? "Incoming call" : "On call  " + Sim.fmtTime(Sim.callSeconds)
                    color: Theme.accentMid
                }
                T { text: Sim.caller; font.pixelSize: 44 }
                T { text: Sim.callerNumber; color: Theme.accentMid; font.pixelSize: Theme.fontSmall }
            }
        }

        Column {
            x: 60
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 44
            width: parent.width - 120
            spacing: 12
            Repeater {
                model: root.actions
                MenuRow {
                    width: parent.width
                    height: 62
                    selected: index === root.sel
                    icon: modelData === "mute" ? (Sim.micMuted ? Icons.micOff : Icons.mic) : modelData === "answer" ? Icons.phone : Icons.hangup
                    label: modelData === "answer" ? "Answer" : modelData === "decline" ? "Decline"
                         : modelData === "mute" ? (Sim.micMuted ? "Microphone off" : "Mute microphone") : "End call"
                    Rectangle {   // outline for the unselected row, as in the vision sheet
                        anchors.fill: parent
                        color: "transparent"
                        border.color: Theme.accent
                        border.width: 2
                        visible: !parent.selected
                    }
                    onClicked: root.run(modelData)
                }
            }
        }
    }
}
