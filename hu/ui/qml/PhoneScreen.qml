import QtQuick

// Phone: favourites / recents / contacts on the left, keypad on the right.
Item {
    id: root
    objectName: "phoneScreen"        // run.py --screenshots opens a contact through it
    property int tab: 0
    property int sel: 0
    property string dialed: ""
    readonly property var tabs: ["Favourites", "Recent", "Contacts"]
    readonly property var rows: tab === 0 ? Sim.favourites : tab === 1 ? Sim.recents : Sim.contacts
    // a contact opened from Contacts: its numbers to call and the favourite switch
    property var detail: null
    property int dsel: 0
    readonly property var detailRows: detail ? detail.numbers.map(n => ({ kind: "number", number: n.number, type: n.type }))
                                                     .concat([{ kind: "fav" }]) : []
    onTabChanged: { sel = 0; detail = null }

    function knob(d) {
        if (detail) dsel = Math.min(detailRows.length - 1, Math.max(0, dsel + d))
        else sel = Math.min(rows.length - 1, Math.max(0, sel + d))
    }
    function side(d) { if (!detail) tab = (tab + d + tabs.length) % tabs.length }
    function press() {
        if (detail) { pressDetail(detailRows[dsel]); return }
        const r = rows[sel]
        if (!r) return
        if (tab === 2) { detail = r; dsel = 0 }
        else if (Sim.phoneConnected) Sim.dial(r.number || r.name)
    }
    function pressDetail(r) {
        if (r.kind === "fav") {
            const on = !Sim.favourites.some(f => f.id === detail.id)
            Sim.setFavourite(detail, on)
        } else if (Sim.phoneConnected) Sim.dial(r.number)
    }
    // main.qml asks before going home: an open contact closes first
    function back() { if (!detail) return false; detail = null; return true }

    Tabs {
        x: Theme.margin
        y: 12
        labels: root.tabs
        current: root.tab
        onSelected: (i) => root.tab = i
    }

    ListView {
        id: list
        visible: !root.detail
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

    // one contact
    Column {
        x: list.x
        y: list.y
        width: list.width
        spacing: 6
        visible: root.detail !== null
        T { x: 14; text: root.detail ? root.detail.name : ""; font.pixelSize: Theme.fontLarge; bottomPadding: 10; width: parent.width - 28; elide: Text.ElideRight }
        Repeater {
            model: root.detailRows
            MenuRow {
                width: list.width
                height: 62
                readonly property bool isFav: root.detail && Sim.favourites.some(f => f.id === root.detail.id)
                icon: modelData.kind === "fav" ? Icons.star : Icons.phone
                label: modelData.kind === "fav" ? (isFav ? "Remove from favourites" : "Add to favourites") : modelData.number
                value: modelData.kind === "fav" ? "" : modelData.type
                selected: index === root.dsel
                onClicked: { root.dsel = index; root.pressDetail(modelData) }
            }
        }
    }

    T {
        x: list.x + 14
        y: list.y + 20
        visible: root.rows.length === 0 && !root.detail
        text: !Sim.phoneConnected ? "No phone connected"
            : ["No favourites yet", "No recent calls", "No contacts"][root.tab]
        color: Theme.accentMid
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
            LineButton { width: 210; icon: Icons.phone; label: "Call"; highlighted: Sim.phoneConnected; iconSize: 24; onClicked: if (root.dialed !== "" && Sim.phoneConnected) Sim.dial(root.dialed) }
        }
    }

    T {
        x: Theme.margin + 14
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 22
        text: Sim.phoneName + (Sim.phoneConnected && Sim.phoneBattery >= 0 ? "  ·  " + Sim.phoneBattery + " %" : "")
        font.pixelSize: Theme.fontSmall
        color: Theme.accentMid
    }
}
