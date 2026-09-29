import QtQuick
import QtQuick.Shapes

// Front view of the Audi A3 Sportback (8PA, 2005) in a 320 x 240 box
// (1765 mm wide, 1423 mm high): single-frame grille, swept headlights,
// round fog lights. Left-hand details are drawn once and mirrored.
Item {
    id: root
    property color color: Theme.accent
    property real stroke: 1.6
    implicitWidth: 320
    implicitHeight: 240

    readonly property color faint: Qt.rgba(color.r, color.g, color.b, 0.55)

    component Half: Shape {
        width: 320; height: 240
        preferredRendererType: Shape.CurveRenderer
        ShapePath {   // headlight, fog/intake, mirror, tyre
            strokeColor: root.color; strokeWidth: root.stroke
            fillColor: "transparent"; capStyle: ShapePath.RoundCap; joinStyle: ShapePath.RoundJoin
            PathSvg { path: "M31 141 L104 146 L109 157 Q72 163 37 160 Q29 154 31 141 Z "
                          + "M36 182 L98 184 L104 202 L44 206 Q35 198 36 182 Z "
                          + "M74 126 L48 118 Q38 117 37 125 Q38 132 48 132 L71 130 "
                          + "M36 220 V233 H78 V220" }
        }
        ShapePath {   // light graphics, creases
            strokeColor: root.faint; strokeWidth: root.stroke * 0.8
            fillColor: "transparent"; capStyle: ShapePath.RoundCap; joinStyle: ShapePath.RoundJoin
            PathSvg { path: "M62 152 A6 6 0 1 1 50 152 A6 6 0 1 1 62 152 "
                          + "M90 154 A6 6 0 1 1 78 154 A6 6 0 1 1 90 154 "
                          + "M36 147 Q70 151 104 151 "
                          + "M63 194 A7 7 0 1 1 49 194 A7 7 0 1 1 63 194 "
                          + "M112 125 L121 140 M28 171 Q70 173 108 171" }
        }
    }

    Item {
        width: 320; height: 240
        anchors.centerIn: parent
        scale: Math.min(root.width / 320, root.height / 240)

        Half {}
        Half { transform: Scale { origin.x: 160; xScale: -1 } }

        Shape {
            width: 320; height: 240
            preferredRendererType: Shape.CurveRenderer
            ShapePath {   // silhouette
                strokeColor: root.color; strokeWidth: root.stroke * 1.35
                fillColor: "transparent"; capStyle: ShapePath.RoundCap; joinStyle: ShapePath.RoundJoin
                PathSvg { path: "M46 220 L34 218 Q27 216 27 206 L27 150 Q27 132 42 128 L62 124 L88 50 "
                              + "Q92 40 104 40 L216 40 Q228 40 232 50 L258 124 L278 128 Q293 132 293 150 "
                              + "L293 206 Q293 216 286 218 L274 220 Z" }
            }
            ShapePath {   // windscreen, bonnet edge, grille
                strokeColor: root.color; strokeWidth: root.stroke
                fillColor: "transparent"; capStyle: ShapePath.RoundCap; joinStyle: ShapePath.RoundJoin
                PathSvg { path: "M73 122 L97 54 Q100 47 109 47 L211 47 Q220 47 223 54 L247 122 Z "
                              + "M42 128 Q160 114 278 128 "
                              + "M122 140 L198 140 L210 154 L206 204 Q204 211 196 211 L124 211 Q116 211 114 204 L110 154 Z" }
            }
            ShapePath {   // grille slats, plate, emblem, mirror, lip, roof rails
                strokeColor: root.faint; strokeWidth: root.stroke * 0.8
                fillColor: "transparent"; capStyle: ShapePath.RoundCap
                PathSvg { path: "M111.5 160 H208.5 M112 168 H208 M112.5 176 H207.5 M113 184 H207 M113.5 192 H206.5 M114 200 H206 "
                              + "M138 178 H182 V191 H138 Z M146 146 H174 V152 H146 Z "
                              + "M154 48 H166 V53 H154 Z M60 220 H260 "
                              + "M106 36 H126 M194 36 H214" }
            }
        }
    }
}
