import QtQuick
import QtQuick.Shapes

// Big line-art arrow for a navigation maneuver (D11, docs/companion-protocol.md):
// the way to take in the accent colour, other roads of the junction dimmed.
// Drawn in a 100 x 100 box, right-hand traffic (roundabouts counter-clockwise).
Item {
    id: root
    property string maneuver: "continue"   // depart, turn, continue, merge, fork, on_ramp, off_ramp, roundabout, uturn, arrive, unknown
    property string modifier: ""           // straight, slight_left, left, sharp_left, slight_right, right, sharp_right
    property int exit: 0                   // roundabout exit, 0 = not known
    property color color: Theme.accent
    property color dimColor: Theme.accentDim
    property real stroke: 8
    implicitWidth: 120
    implicitHeight: 120

    readonly property real side: modifier.indexOf("left") >= 0 ? -1 : 1
    readonly property real turnAngle: ({ straight: 0, slight_left: -45, left: -90, sharp_left: -135,
                                         slight_right: 45, right: 90, sharp_right: 135 })[modifier] || 0

    function f(v) { return v.toFixed(1) }
    function head(x, y, deg) {       // arrow head at (x, y) pointing at deg (0 = up, 90 = right)
        const a = deg * Math.PI / 180, l = 15, s = 0.62;
        const bx = Math.sin(a), by = -Math.cos(a);
        return " M" + f(x - l * (bx * Math.cos(s) - by * Math.sin(s))) + " " + f(y - l * (by * Math.cos(s) + bx * Math.sin(s)))
             + " L" + f(x) + " " + f(y)
             + " L" + f(x - l * (bx * Math.cos(-s) - by * Math.sin(-s))) + " " + f(y - l * (by * Math.cos(-s) + bx * Math.sin(-s)));
    }
    function turn(deg, len) {        // stem from the bottom, bend at the junction, leave at deg
        const a = deg * Math.PI / 180, ex = 50 + len * Math.sin(a), ey = 50 - len * Math.cos(a);
        return "M50 94 L50 63 Q50 50 " + f(50 + 13 * Math.sin(a)) + " " + f(50 - 13 * Math.cos(a))
             + " L" + f(ex) + " " + f(ey) + head(ex, ey, deg);
    }
    readonly property real exitAngle: Math.min(Math.max(exit, 1) * 90, 315)   // from the entry, counter-clockwise
    readonly property var paths: {
        const m = maneuver;
        if (m === "turn" || m === "on_ramp" || m === "off_ramp" || m === "continue" || m === "depart")
            return { main: turn(m === "on_ramp" || m === "off_ramp" ? side * 40 : turnAngle, 38),
                     dim: m === "off_ramp" ? "M50 50 L50 8" : "" };
        if (m === "fork")
            return { main: turn(side * 32, 40), dim: "M50 63 Q50 50 " + f(50 - side * 7) + " " + f(50 - 11) + " L" + f(50 - side * 21) + " 14" };
        if (m === "merge")
            // our road joins from the other side and moves over into the lane (modifier = direction we move)
            return { main: "M" + f(50 - side * 32) + " 94 Q" + f(50 - side * 32) + " 60 50 44 L50 10" + head(50, 10, 0), dim: "M50 94 L50 44" };
        if (m === "uturn")
            return { main: "M62 94 L62 42 A14 14 0 0 0 34 42 L34 72" + head(34, 72, 180), dim: "" };
        if (m === "roundabout") {
            const r = 19, cy = 48, a = exitAngle * Math.PI / 180;
            const px = 50 + r * Math.sin(a), py = cy + r * Math.cos(a);
            const ex = 50 + (r + 24) * Math.sin(a), ey = cy + (r + 24) * Math.cos(a);
            return { main: "M50 94 L50 " + (cy + r) + " A" + r + " " + r + " 0 " + (exitAngle > 180 ? 1 : 0) + " 0 " + f(px) + " " + f(py)
                           + " L" + f(ex) + " " + f(ey) + head(ex, ey, 180 - exitAngle),
                     dim: Icons.circle(50, cy, r) };
        }
        if (m === "arrive")
            return { main: "M38 94 L38 12 M38 14 L76 14 L66 31 L76 48 L38 48", dim: "M22 94 L78 94" };
        return { main: "", dim: "M50 94 L50 10" + head(50, 10, 0) };   // unknown: the screen shows the app's text
    }

    Shape {
        width: 100; height: 100
        anchors.centerIn: parent
        scale: Math.min(root.width, root.height) / 100
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            strokeColor: root.dimColor; strokeWidth: root.stroke; fillColor: "transparent"
            capStyle: ShapePath.RoundCap; joinStyle: ShapePath.RoundJoin
            PathSvg { path: root.paths.dim }
        }
        ShapePath {
            strokeColor: root.color; strokeWidth: root.stroke; fillColor: "transparent"
            capStyle: ShapePath.RoundCap; joinStyle: ShapePath.RoundJoin
            PathSvg { path: root.paths.main }
        }
    }
    // roundabout exit number in the middle of the circle
    T {
        visible: root.maneuver === "roundabout" && root.exit > 0
        anchors.horizontalCenter: parent.horizontalCenter
        y: root.height / 2 + (48 - 50) * Math.min(root.width, root.height) / 100 - height / 2
        text: root.exit
        color: root.color
        font.family: Theme.numberFamily
        font.pixelSize: Math.min(root.width, root.height) * 0.24
    }
}
