import QtQuick

// Outlined button; filled when active/highlighted.
Item {
    id: root
    property string icon: ""
    property string label: ""
    property bool highlighted: false
    property bool round: false
    property real iconSize: 30
    signal clicked()
    implicitWidth: round ? 72 : Math.max(72, content.implicitWidth + 40)
    implicitHeight: round ? 72 : 56

    Rectangle {
        anchors.fill: parent
        radius: root.round ? width / 2 : 3
        color: root.highlighted ? Theme.accent : (mouse.pressed ? Theme.accentFaint : "transparent")
        border.color: Theme.accent
        border.width: 2
    }
    Row {
        id: content
        anchors.centerIn: parent
        spacing: 10
        Icon {
            visible: root.icon !== ""
            path: root.icon
            width: root.iconSize; height: root.iconSize
            stroke: 1.8
            color: root.highlighted ? Theme.textOnAccent : Theme.accent
            anchors.verticalCenter: parent.verticalCenter
        }
        T {
            visible: root.label !== ""
            text: root.label
            color: root.highlighted ? Theme.textOnAccent : Theme.accent
            anchors.verticalCenter: parent.verticalCenter
        }
    }
    MouseArea { id: mouse; anchors.fill: parent; onClicked: root.clicked() }
}
