import QtQuick
import QtQuick.Shapes

// Side view of the Audi A3 Sportback (8PA, 2005), drawn to its real proportions
// (4285 mm long, 2578 mm wheelbase, 1423 mm high, 17" wheels) in a 500 x 170 box.
// Heavy line = silhouette, medium = glass and wheels, faint = panel detail.
Item {
    id: root
    property color color: Theme.accent
    property real stroke: 1.6
    implicitWidth: 500
    implicitHeight: 170

    function wheel(cx, cy) {
        function c(r) { return "M" + (cx + r) + " " + cy + " A" + r + " " + r + " 0 1 1 " + (cx - r) + " " + cy
                             + " A" + r + " " + r + " 0 1 1 " + (cx + r) + " " + cy + " "; }
        let s = c(34) + c(25) + c(5);
        for (let i = 0; i < 5; i++) {           // five double spokes
            const a = -Math.PI / 2 + i * 2 * Math.PI / 5;
            for (const o of [-0.13, 0.13]) {
                s += "M" + (cx + 6 * Math.cos(a + o * 2)).toFixed(1) + " " + (cy + 6 * Math.sin(a + o * 2)).toFixed(1)
                   + " L" + (cx + 24 * Math.cos(a + o)).toFixed(1) + " " + (cy + 24 * Math.sin(a + o)).toFixed(1) + " ";
            }
        }
        return s;
    }

    Shape {
        width: 500; height: 170
        anchors.centerIn: parent
        scale: Math.min(root.width / 500, root.height / 170)
        preferredRendererType: Shape.CurveRenderer

        // ground shadow
        ShapePath {
            strokeColor: Qt.rgba(root.color.r, root.color.g, root.color.b, 0.25); strokeWidth: root.stroke
            fillColor: "transparent"; capStyle: ShapePath.RoundCap
            PathSvg { path: "M30 165 H470" }
        }
        // panel detail
        ShapePath {
            strokeColor: Qt.rgba(root.color.r, root.color.g, root.color.b, 0.55); strokeWidth: root.stroke * 0.8
            fillColor: "transparent"; capStyle: ShapePath.RoundCap; joinStyle: ShapePath.RoundJoin
            // shoulder line, sill line, door cuts, handles, bumper lines, roof rail
            PathSvg { path: "M66 106 Q280 98 470 90 M144 140 Q250 142 360 140 "
                          + "M160 83 L160 147 M296 76 L298 147 M378 72 L380 112 "
                          + "M238 102 H256 M338 100 H356 "
                          + "M18 132 Q44 136 70 134 M438 136 H488 M140 147 H362 "
                          + "M252 8 Q320 0 420 9 M266 6 V11 M406 7 V12" }
        }
        // glass, lights, mirror
        ShapePath {
            strokeColor: root.color; strokeWidth: root.stroke
            fillColor: "transparent"; capStyle: ShapePath.RoundCap; joinStyle: ShapePath.RoundJoin
            PathSvg { path: "M162 79 Q200 36 244 22 L290 20 L292 75 Z "
                          + "M300 21 L372 21 L373 71 L300 74 Z "
                          + "M381 21 L424 25 Q438 29 444 40 L448 64 L381 70 Z "
                          + "M12 110 L72 101 L66 113 Q40 118 16 118 Z M24 111 L22 117 "
                          + "M462 68 L487 74 L488 92 L458 88 Z "
                          + "M172 88 Q166 78 154 80 L150 89 Q160 92 172 91" }
        }
        // silhouette
        ShapePath {
            strokeColor: root.color; strokeWidth: root.stroke * 1.35
            fillColor: "transparent"; capStyle: ShapePath.RoundCap; joinStyle: ShapePath.RoundJoin
            PathSvg { path: "M16 150 Q9 140 9 120 Q9 108 14 104 L24 98 Q86 88 156 80 "
                          + "Q198 28 244 15 Q300 6 350 9 Q410 12 450 20 L458 27 "
                          + "L478 62 Q486 74 488 86 Q491 110 490 138 Q489 150 482 150 "
                          + "L429.6 150 A40 40 0 1 0 362.4 150 "
                          + "L141.6 150 A40 40 0 1 0 74.4 150 Z" }
        }
        // wheels
        ShapePath {
            strokeColor: root.color; strokeWidth: root.stroke
            fillColor: "transparent"; capStyle: ShapePath.RoundCap; joinStyle: ShapePath.RoundJoin
            PathSvg { path: root.wheel(108, 130) + root.wheel(396, 130) }
        }
    }
}
