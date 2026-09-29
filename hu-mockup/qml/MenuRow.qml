import QtQuick

// One selectable list row: icon + label, filled bar when selected.
Item {
    id: root
    property string icon: ""
    property string label: ""
    property string value: ""
    property bool selected: false
    property bool chevron: false
    signal clicked()
    height: 60

    Rectangle {
        anchors.fill: parent
        color: Theme.accent
        opacity: root.selected ? 0.92 : (mouse.pressed ? 0.25 : 0)
        Behavior on opacity { NumberAnimation { duration: 120 } }
    }
    Row {
        anchors.left: parent.left
        anchors.leftMargin: 14
        anchors.verticalCenter: parent.verticalCenter
        spacing: 18
        Icon {
            visible: root.icon !== ""
            path: root.icon
            width: 32; height: 32
            color: root.selected ? Theme.textOnAccent : Theme.accent
            anchors.verticalCenter: parent.verticalCenter
        }
        T {
            text: root.label
            color: root.selected ? Theme.textOnAccent : Theme.accent
            anchors.verticalCenter: parent.verticalCenter
        }
    }
    T {
        anchors.right: parent.right
        anchors.rightMargin: root.chevron ? 44 : 14
        anchors.verticalCenter: parent.verticalCenter
        text: root.value
        color: root.selected ? Theme.textOnAccent : Theme.accentMid
    }
    Icon {
        visible: root.chevron
        path: Icons.chevronRight
        width: 24; height: 24
        anchors.right: parent.right
        anchors.rightMargin: 12
        anchors.verticalCenter: parent.verticalCenter
        color: root.selected ? Theme.textOnAccent : Theme.accentMid
    }
    MouseArea { id: mouse; anchors.fill: parent; onClicked: root.clicked() }
}
