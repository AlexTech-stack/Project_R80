import QtQuick
import QtQuick.Shapes

// Draws one of the Icons.* path strings (24x24 design box) in the accent colour.
Item {
    id: root
    property string path
    property color color: Theme.accent
    property real stroke: 1.6
    property bool filled: false
    implicitWidth: 32
    implicitHeight: 32

    Shape {
        width: 24; height: 24
        anchors.centerIn: parent
        scale: Math.min(root.width, root.height) / 24
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            strokeColor: root.color
            strokeWidth: root.stroke
            fillColor: root.filled ? root.color : "transparent"
            capStyle: ShapePath.RoundCap
            joinStyle: ShapePath.RoundJoin
            PathSvg { path: root.path }
        }
    }
}
