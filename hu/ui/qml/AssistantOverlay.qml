import QtQuick

// The voice assistant (hu-assistd) at the bottom of any screen while it runs: what it does
// (listening, thinking, speaking), what it heard and its answer. Not modal: the screen below
// keeps working. When a start is refused (switched off, still loading, a call) it says why.
Item {
    id: root
    readonly property bool active: Sim.assistantState !== "idle"
    readonly property string st: Sim.assistantState
    property string toast: ""
    visible: opacity > 0
    opacity: active || toast !== "" ? 1 : 0
    Behavior on opacity { NumberAnimation { duration: 200 } }

    Connections {
        target: Sim
        function onAssistantNoticeChanged() {
            if (Sim.assistantNotice === "" || root.active) return
            root.toast = "Voice assistant: " + Sim.assistantNotice
            toastTimer.restart()
        }
    }
    Timer { id: toastTimer; interval: 3500; onTriggered: root.toast = "" }

    Rectangle {
        id: box
        width: 960
        height: root.active ? 196 : 84
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 26
        color: Theme.bg
        border.color: Theme.accent
        border.width: 2
        radius: 6
        MouseArea { anchors.fill: parent; onClicked: if (root.active) Sim.assistantStop() }   // a tap stops it

        // the microphone in a ring: pulses while listening, a turning arc while thinking,
        // waves while speaking
        Item {
            id: badge
            visible: root.active
            x: 34; width: 116; height: 116
            anchors.verticalCenter: parent.verticalCenter
            Rectangle {
                anchors.fill: parent; radius: width / 2
                color: root.st === "listening" ? Theme.accentFaint : "transparent"
                border.color: Theme.accent; border.width: 2
            }
            Icon { anchors.centerIn: parent; width: 56; height: 56; path: Icons.mic; stroke: 1.5 }
            Rectangle {
                id: pulse
                anchors.centerIn: parent
                width: parent.width; height: width; radius: width / 2
                color: "transparent"; border.color: Theme.accent; border.width: 2
                visible: root.st === "listening"
                SequentialAnimation on scale {
                    running: pulse.visible; loops: Animation.Infinite
                    NumberAnimation { from: 1; to: 1.35; duration: 900 }
                }
                SequentialAnimation on opacity {
                    running: pulse.visible; loops: Animation.Infinite
                    NumberAnimation { from: 0.9; to: 0; duration: 900 }
                }
            }
            Canvas {
                id: arc
                anchors.fill: parent
                anchors.margins: -10
                visible: root.st === "thinking"
                onPaint: {
                    const c = getContext("2d"); c.reset()
                    c.strokeStyle = Theme.accent; c.lineWidth = 3
                    c.beginPath(); c.arc(width / 2, height / 2, width / 2 - 2, 0, Math.PI * 0.6); c.stroke()
                }
                RotationAnimation on rotation { running: arc.visible; loops: Animation.Infinite; from: 0; to: 360; duration: 1100 }
            }
            Row {
                anchors.left: parent.right; anchors.leftMargin: 6
                anchors.verticalCenter: parent.verticalCenter
                spacing: 5
                visible: root.st === "speaking" || root.st === "greeting"
                Repeater {
                    model: 3
                    Rectangle {
                        width: 3; height: 34; radius: 1.5; color: Theme.accent
                        anchors.verticalCenter: parent.verticalCenter
                        SequentialAnimation on height {
                            running: parent.visible; loops: Animation.Infinite
                            PauseAnimation { duration: index * 120 }
                            NumberAnimation { to: 12; duration: 300 }
                            NumberAnimation { to: 34; duration: 300 }
                        }
                    }
                }
            }
        }

        Column {
            visible: root.active
            x: 196
            width: parent.width - x - 36
            anchors.verticalCenter: parent.verticalCenter
            spacing: 8
            Row {
                spacing: 18
                T {
                    text: root.st === "greeting" ? "I'm here" : root.st === "listening" ? "Listening …"
                        : root.st === "thinking" ? "Thinking …" : "Speaking"
                    font.pixelSize: Theme.fontLarge
                }
                T {
                    visible: Sim.assistantMode === "conversation"
                    anchors.verticalCenter: parent.verticalCenter
                    text: "CONVERSATION"
                    color: Theme.accentMid
                    font.pixelSize: Theme.fontSmall
                    font.letterSpacing: 2
                }
            }
            T {
                width: parent.width
                visible: Sim.assistantHeard !== ""
                text: "“" + Sim.assistantHeard + "”"
                color: Theme.accentMid
                font.pixelSize: Theme.fontSmall + 2
            }
            T {
                width: parent.width
                visible: Sim.assistantAnswer !== "" && root.st === "speaking"
                text: Sim.assistantAnswer
                wrapMode: Text.WordWrap
                maximumLineCount: 3
                font.pixelSize: Theme.fontNormal
            }
        }

        T {
            visible: !root.active
            anchors.centerIn: parent
            text: root.toast
            color: Theme.accentMid
        }
    }
}
