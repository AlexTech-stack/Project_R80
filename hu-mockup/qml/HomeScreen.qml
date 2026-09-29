import QtQuick

// Main menu: list on the left, car + quick status on the right.
Item {
    id: root
    readonly property var items: [
        { key: "navigation", label: "Navigation",      icon: Icons.nav },
        { key: "media",      label: "Media",           icon: Icons.music },
        { key: "radio",      label: "Radio",           icon: Icons.radio },
        { key: "phone",      label: "Phone",           icon: Icons.phone },
        { key: "vehicle",    label: "Vehicle",         icon: Icons.car },
        { key: "cluster",    label: "Drive",           icon: Icons.gauge },
        { key: "clock",      label: "Clock & Weather", icon: Icons.clock },
        { key: "settings",   label: "Settings",        icon: Icons.gear }
    ]
    property int sel: Sim.homeIndex
    onSelChanged: Sim.homeIndex = sel

    function knob(d) { sel = (sel + d + items.length) % items.length }
    function press() { Sim.navigate(items[sel].key) }

    Column {
        id: menu
        x: Theme.margin
        y: 22
        width: 420
        spacing: 11
        Repeater {
            model: root.items
            MenuRow {
                width: menu.width
                height: 64
                icon: modelData.icon
                label: modelData.label
                selected: index === root.sel
                onClicked: { root.sel = index; root.press() }
            }
        }
    }

    Rectangle {
        x: menu.x + menu.width + 40
        y: 30
        width: 1; height: parent.height - 60
        color: Theme.accentDim
    }

    CarFront {
        x: 540
        y: 40
        width: 680; height: 440
        stroke: 1.1
    }

    // quick status tiles
    Row {
        x: 560
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 40
        spacing: 0
        Repeater {
            model: [
                { icon: Icons.nav,   top: Sim.navGuidance ? Sim.nextManeuver.km.toFixed(1) + " km" : "--", sub: Sim.nextManeuver.street, key: "navigation" },
                { icon: Icons.music, top: Sim.track.title, sub: Sim.track.artist, key: "media" },
                { icon: Icons.fuel,  top: Sim.rangeKm + " km", sub: "Range", key: "vehicle" }
            ]
            Item {
                width: 220; height: 110
                Rectangle { visible: index > 0; width: 1; height: parent.height; color: Theme.accentDim }
                Column {
                    anchors.left: parent.left
                    anchors.leftMargin: index > 0 ? 22 : 0
                    anchors.right: parent.right
                    anchors.rightMargin: 12
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 6
                    Icon { path: modelData.icon; width: 30; height: 30 }
                    T { width: parent.width; text: modelData.top; font.pixelSize: Theme.fontNormal }
                    T { width: parent.width; text: modelData.sub; color: Theme.accentMid; font.pixelSize: Theme.fontSmall }
                }
                MouseArea { anchors.fill: parent; onClicked: Sim.navigate(modelData.key) }
            }
        }
    }
}
