import QtQuick

// The first time a phone connects: may the HU keep a copy of its contacts and call history?
// The answer is kept per phone (hu-phoned); Settings -> Phone changes it later.
Item {
    id: root
    visible: Sim.askPhoneConsent && Sim.callState === "idle"
    property int sel: 0
    readonly property var actions: ["copy", "notnow"]
    onVisibleChanged: sel = 0

    function knob(d) { sel = (sel + d + actions.length) % actions.length }
    function press() { run(actions[sel]) }
    function run(a) { Sim.phoneSetConsent(a === "copy") }

    Rectangle { anchors.fill: parent; color: Theme.shade; opacity: 0.72 }
    MouseArea { anchors.fill: parent }  // modal

    Rectangle {
        width: 760; height: 470
        anchors.centerIn: parent
        anchors.verticalCenterOffset: 30
        color: Theme.bg
        border.color: Theme.accent
        border.width: 2
        radius: 6

        Row {
            x: 60; y: 56
            spacing: 36
            Icon { width: 72; height: 72; path: Icons.person; stroke: 1.5 }
            Column {
                width: 520
                spacing: 10
                T { text: Sim.phoneName; font.pixelSize: Theme.fontLarge; width: parent.width; elide: Text.ElideRight }
                T {
                    width: parent.width
                    wrapMode: Text.WordWrap
                    color: Theme.accentMid
                    text: "Copy this phone's contacts and call history to the headunit? "
                        + "Settings → Phone syncs or deletes the copy later."
                }
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
                    icon: modelData === "copy" ? Icons.person : Icons.back
                    label: modelData === "copy" ? "Copy contacts" : "Not now"
                    Rectangle {
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
