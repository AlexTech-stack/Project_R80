import QtQuick

// Horizontal tab strip with an underline on the active tab.
Row {
    id: root
    property var labels: []
    property int current: 0
    signal selected(int index)
    spacing: 36
    Repeater {
        model: root.labels
        Item {
            width: lbl.implicitWidth
            height: 44
            T {
                id: lbl
                text: modelData
                color: index === root.current ? Theme.accent : Theme.accentDim
                anchors.verticalCenter: parent.verticalCenter
            }
            Rectangle {
                anchors.bottom: parent.bottom
                width: parent.width; height: 3
                color: Theme.accent
                visible: index === root.current
            }
            MouseArea { anchors.fill: parent; anchors.margins: -8; onClicked: root.selected(index) }
        }
    }
}
