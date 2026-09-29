import QtQuick

// Placeholder brand mark (the real Audi rings are a trademark).
Item {
    id: root
    implicitWidth: 96
    implicitHeight: 30
    property color color: Theme.accent
    Rectangle {
        anchors.fill: parent
        radius: height / 2
        color: "transparent"
        border.color: root.color
        border.width: 2
    }
    Text {
        anchors.centerIn: parent
        text: "R80"
        color: root.color
        font.family: Theme.numberFamily
        font.pixelSize: root.height * 0.62
        font.letterSpacing: root.height * 0.12
    }
}
