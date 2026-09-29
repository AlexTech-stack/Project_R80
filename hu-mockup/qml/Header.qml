import QtQuick

// Top bar: title (or logo) on the left, status icons and clock on the right.
Item {
    id: root
    property string title: ""
    property bool showBack: title !== ""
    signal back()
    height: Theme.headerHeight

    Row {
        id: left
        anchors.left: parent.left
        anchors.leftMargin: Theme.margin - (root.showBack ? 12 : 0)
        anchors.verticalCenter: parent.verticalCenter
        spacing: 6
        Icon {
            visible: root.showBack
            path: Icons.back
            width: 34; height: 34
            anchors.verticalCenter: parent.verticalCenter
        }
        T {
            visible: root.title !== ""
            text: root.title
            font.pixelSize: Theme.fontLarge
            anchors.verticalCenter: parent.verticalCenter
        }
        Logo {
            visible: root.title === ""
            anchors.verticalCenter: parent.verticalCenter
        }
    }
    MouseArea {
        anchors.fill: left
        anchors.margins: -12
        enabled: root.showBack
        onClicked: root.back()
    }

    Row {
        anchors.right: parent.right
        anchors.rightMargin: Theme.margin
        anchors.verticalCenter: parent.verticalCenter
        spacing: 22
        Row {
            spacing: 6
            anchors.verticalCenter: parent.verticalCenter
            visible: Sim.callState === "active"
            Icon { path: Icons.phone; width: 24; height: 24; anchors.verticalCenter: parent.verticalCenter }
            T { text: Sim.fmtTime(Sim.callSeconds); font.pixelSize: Theme.fontSmall }
        }
        T {
            text: Math.round(Sim.outsideTemp) + "°C"
            color: Theme.accentMid
            font.pixelSize: Theme.fontSmall + 2
            anchors.verticalCenter: parent.verticalCenter
        }
        Icon { path: Icons.bluetooth; width: 24; height: 24; color: Theme.accentMid; anchors.verticalCenter: parent.verticalCenter }
        T { text: Sim.timeText; font.pixelSize: Theme.fontNormal + 2; anchors.verticalCenter: parent.verticalCenter }
        Icon { path: Icons.signal; filled: true; stroke: 0.6; width: 26; height: 26; anchors.verticalCenter: parent.verticalCenter }
    }

    Rectangle {
        anchors.bottom: parent.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.leftMargin: Theme.margin
        anchors.rightMargin: Theme.margin
        height: 2
        color: Theme.accent
    }
}
