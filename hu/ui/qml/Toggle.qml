import QtQuick

Item {
    id: root
    property bool checked: false
    signal toggled()
    implicitWidth: 66
    implicitHeight: 34
    Rectangle {
        anchors.fill: parent
        radius: height / 2
        color: root.checked ? Theme.accent : "transparent"
        border.color: root.checked ? Theme.accent : Theme.accentDim
        border.width: 2
    }
    Rectangle {
        width: parent.height - 10; height: width; radius: width / 2
        anchors.verticalCenter: parent.verticalCenter
        x: root.checked ? parent.width - width - 5 : 5
        color: root.checked ? Theme.textOnAccent : Theme.accentDim
        Behavior on x { NumberAnimation { duration: 120 } }
    }
    MouseArea { anchors.fill: parent; anchors.margins: -8; onClicked: root.toggled() }
}
