import QtQuick

// Phone: favourites / recents / contacts on the left, keypad on the right.
Item {
    id: root
    property int tab: 0
    property int sel: 0
    property string dialed: ""
    readonly property var tabs: ["Favourites", "Recent", "Contacts"]
    readonly property var rows: tab === 0 ? Sim.contacts.filter(c => c.fav)
                               : tab === 1 ? Sim.recents : Sim.contacts
    onTabChanged: sel = 0

    function knob(d) { sel = Math.min(rows.length - 1, Math.max(0, sel + d)) }
    function side(d) { tab = (tab + d + tabs.length) % tabs.length }
    function press() { Sim.dial(rows[sel].name) }

    Tabs {
        x: Theme.margin
        y: 12
        labels: root.tabs
        current: root.tab
        onSelected: (i) => root.tab = i
    }

    ListView {
        id: list
        x: Theme.margin
        y: 80
        width: 640
        height: parent.height - 100
        clip: true
        spacing: 6
        model: root.rows
        currentIndex: root.sel
        delegate: MenuRow {
            width: list.width
            height: 62
            icon: root.tab === 1 ? (modelData.kind === "in" ? Icons.callIn : modelData.kind === "out" ? Icons.callOut : Icons.callMissed)
                                 : (modelData.fav ? Icons.star : Icons.person)
            label: modelData.name
            value: root.tab === 1 ? modelData.when : modelData.number
            selected: index === root.sel
            onClicked: { root.sel = index; root.press() }
        }
    }

    Rectangle { x: list.x + list.width + 30; y: 30; width: 1; height: parent.height - 60; color: Theme.accentDim }

    // keypad
    Item {
        x: list.x + list.width + 70
        y: 16
        width: parent.width - x - Theme.margin
        height: parent.height - 32

        Rectangle {
            id: display
            width: parent.width; height: 60
            color: "transparent"
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 2; color: Theme.accentDim }
            T {
                anchors.centerIn: parent
                text: root.dialed === "" ? "Enter number" : root.dialed
                color: root.dialed === "" ? Theme.accentDim : Theme.accent
                font.family: Theme.monoFamily
                font.pixelSize: Theme.fontLarge
            }
        }
        Grid {
            anchors.horizontalCenter: parent.horizontalCenter
            y: 84
            columns: 3
            columnSpacing: 26
            rowSpacing: 14
            Repeater {
                model: ["1", "2", "3", "4", "5", "6", "7", "8", "9", "*", "0", "#"]
                LineButton {
                    width: 120; height: 72
                    label: modelData
                    onClicked: if (root.dialed.length < 16) root.dialed += modelData
                }
            }
        }
        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom
            spacing: 26
            LineButton { width: 180; icon: Icons.back; label: "Delete"; iconSize: 22; onClicked: root.dialed = root.dialed.slice(0, -1) }
            LineButton { width: 210; icon: Icons.phone; label: "Call"; highlighted: true; iconSize: 24; onClicked: if (root.dialed !== "") Sim.dial(root.dialed) }
        }
    }

    T {
        x: Theme.margin + 14
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 22
        text: Sim.phoneName + "  ·  " + Sim.phoneBattery + " %"
        font.pixelSize: Theme.fontSmall
        color: Theme.accentMid
    }
}
