import QtQuick
import QtQuick.Shapes

// Moving line-art map with a simulated route, plus a guidance panel.
Item {
    id: root

    function knob(d) { Sim.mapZoom = Math.min(2.2, Math.max(0.5, Sim.mapZoom * (d < 0 ? 1.15 : 1 / 1.15))) }
    function press() { Sim.headingUp = !Sim.headingUp }

    // ---- map ------------------------------------------------------------
    Item {
        id: mapView
        x: Theme.margin
        y: 18
        width: 820
        height: parent.height - 36
        clip: true

        // own position on screen
        readonly property real vx: width / 2
        readonly property real vy: height * 0.68

        PathInterpolator {
            id: pos
            path: Path { PathSvg { path: Sim.routePath } }
            progress: Sim.navProgress
        }

        Item {
            id: map
            width: 2000; height: 2000
            transform: [
                Translate { x: -pos.x; y: -pos.y },
                Rotation { angle: Sim.headingUp ? -pos.angle - 90 : 0 },
                Scale { xScale: Sim.mapZoom; yScale: Sim.mapZoom },
                Translate { x: mapView.vx; y: mapView.vy }
            ]

            // procedurally generated streets (seeded, so always the same town)
            readonly property var roads: {
                let seed = 7;
                function rnd() { seed = (seed * 16807) % 2147483647; return (seed - 1) / 2147483646; }
                const minor = [], major = [];
                for (let i = 0; i < 16; i++) {           // north-south streets
                    let x = 40 + i * 130 + rnd() * 40, s = "M" + x.toFixed(0) + " -100";
                    for (let y = 0; y <= 2100; y += 150) { x += (rnd() - 0.5) * 50; s += " L" + x.toFixed(0) + " " + y; }
                    (i % 5 === 2 ? major : minor).push(s);
                }
                for (let j = 0; j < 16; j++) {           // east-west streets
                    let y = 30 + j * 130 + rnd() * 40, s = "M-100 " + y.toFixed(0);
                    for (let x = 0; x <= 2100; x += 150) { y += (rnd() - 0.5) * 50; s += " L" + x + " " + y.toFixed(0); }
                    (j % 6 === 3 ? major : minor).push(s);
                }
                for (let k = 0; k < 10; k++) {           // short lanes
                    const x = rnd() * 2000, y = rnd() * 2000, a = rnd() * Math.PI;
                    minor.push("M" + x.toFixed(0) + " " + y.toFixed(0) + " Q" + (x + 90 * Math.cos(a + 0.6)).toFixed(0) + " " + (y + 90 * Math.sin(a + 0.6)).toFixed(0)
                               + " " + (x + 180 * Math.cos(a)).toFixed(0) + " " + (y + 180 * Math.sin(a)).toFixed(0));
                }
                return { minor: minor.join(" "), major: major.join(" ") };
            }

            Shape {
                anchors.fill: parent
                preferredRendererType: Shape.CurveRenderer
                // river
                ShapePath {
                    strokeColor: "transparent"
                    fillColor: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.07)
                    PathSvg { path: "M-100 250 C300 380 500 150 900 330 C1300 510 1500 300 2100 420 L2100 520 C1500 400 1300 610 900 440 C500 260 300 490 -100 360 Z" }
                }
                // park
                ShapePath {
                    strokeColor: Theme.accentDim; strokeWidth: 1.5
                    strokeStyle: ShapePath.DashLine; dashPattern: [3, 4]
                    fillColor: "transparent"
                    PathSvg { path: "M1200 1600 L1450 1560 L1500 1800 L1260 1850 Z M300 900 L560 880 L600 1100 L320 1150 Z" }
                }
                ShapePath {
                    strokeColor: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.30)
                    strokeWidth: 3; fillColor: "transparent"
                    capStyle: ShapePath.RoundCap; joinStyle: ShapePath.RoundJoin
                    PathSvg { path: map.roads.minor }
                }
                ShapePath {
                    strokeColor: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.55)
                    strokeWidth: 6; fillColor: "transparent"
                    capStyle: ShapePath.RoundCap; joinStyle: ShapePath.RoundJoin
                    PathSvg { path: map.roads.major }
                }
                // the route itself
                ShapePath {
                    strokeColor: Theme.accent
                    strokeWidth: 9; fillColor: "transparent"
                    capStyle: ShapePath.RoundCap; joinStyle: ShapePath.RoundJoin
                    PathSvg { path: Sim.routePath }
                }
            }
            // street labels
            Repeater {
                model: Sim.routePoints.length - 1
                T {
                    readonly property var a: Sim.routePoints[index]
                    readonly property var b: Sim.routePoints[index + 1]
                    x: (a[0] + b[0]) / 2 + 16
                    y: (a[1] + b[1]) / 2 - 12
                    text: Sim.routeStreets[index]
                    font.pixelSize: 17
                    color: Theme.accentMid
                    rotation: Sim.headingUp ? pos.angle + 90 : 0
                }
            }
            // destination flag
            Icon {
                x: Sim.routePoints[Sim.routePoints.length - 1][0] - 4
                y: Sim.routePoints[Sim.routePoints.length - 1][1] - 40
                width: 40; height: 40
                path: Icons.flag
                stroke: 2
                rotation: Sim.headingUp ? pos.angle + 90 : 0
            }
        }

        // own-car arrow
        Shape {
            x: mapView.vx - 22; y: mapView.vy - 28
            width: 44; height: 52
            rotation: Sim.headingUp ? 0 : pos.angle + 90
            transformOrigin: Item.Center
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
                strokeColor: Theme.bg; strokeWidth: 3
                fillColor: Theme.accent
                joinStyle: ShapePath.RoundJoin
                PathSvg { path: "M22 2 L41 48 L22 37 L3 48 Z" }
            }
        }

        // frame
        Rectangle {
            anchors.fill: parent
            color: "transparent"
            border.color: Theme.accentDim
            border.width: 1
        }

        // scale bar
        Column {
            x: 16
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 14
            spacing: 2
            T { text: Math.round(200 / Sim.mapZoom / 10) * 10 + " m"; font.pixelSize: Theme.fontSmall }
            Shape {
                width: 64; height: 10
                ShapePath {
                    strokeColor: Theme.accent; strokeWidth: 2; fillColor: "transparent"
                    PathSvg { path: "M1 0 V9 H63 V0" }
                }
            }
        }

        // current street
        Rectangle {
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 14
            width: street.implicitWidth + 36; height: 40
            color: Theme.bg
            border.color: Theme.accentDim
            radius: 3
            T { id: street; anchors.centerIn: parent; text: Sim.currentStreet; font.pixelSize: Theme.fontSmall }
        }

        // zoom / orientation buttons
        Column {
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 14
            spacing: 10
            LineButton { width: 56; height: 56; icon: Icons.plus; iconSize: 26; onClicked: root.knob(-1) }
            LineButton { width: 56; height: 56; icon: Icons.minus; iconSize: 26; onClicked: root.knob(1) }
            LineButton { width: 56; height: 56; icon: Sim.headingUp ? Icons.headingUp : Icons.compassN; iconSize: 30; onClicked: root.press() }
        }
    }

    // ---- guidance panel ---------------------------------------------------
    Item {
        x: mapView.x + mapView.width + 30
        y: 18
        width: parent.width - x - Theme.margin
        height: mapView.height

        Column {
            width: parent.width
            spacing: 8
            Icon {
                width: 120; height: 120
                stroke: 2.2
                path: Sim.nextManeuver.type === "right" ? Icons.turnRight
                    : Sim.nextManeuver.type === "left" ? Icons.turnLeft
                    : Sim.nextManeuver.type === "flag" ? Icons.flag : Icons.straight
            }
            Row {
                spacing: 8
                T {
                    text: Sim.nextManeuver.km < 1 ? (Math.round(Sim.nextManeuver.km * 100) * 10).toString() : Sim.nextManeuver.km.toFixed(1)
                    font.family: Theme.numberFamily
                    font.pixelSize: 72
                }
                T {
                    text: Sim.nextManeuver.km < 1 ? "m" : "km"
                    font.pixelSize: Theme.fontLarge
                    anchors.baseline: parent.children[0].baseline
                }
            }
            T {
                width: parent.width
                text: Sim.nextManeuver.street
                font.pixelSize: Theme.fontLarge
            }
        }

        Column {
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 6
            width: parent.width
            spacing: 14
            Rectangle { width: parent.width; height: 1; color: Theme.accentDim }
            Row {
                spacing: 12
                Icon { path: Icons.flag; width: 28; height: 28; anchors.verticalCenter: parent.verticalCenter }
                T { text: Sim.destination; font.pixelSize: Theme.fontSmall; color: Theme.accentMid; width: 300 }
            }
            Row {
                spacing: 22
                Column {
                    T { text: "Arrival"; font.pixelSize: Theme.fontSmall; color: Theme.accentMid }
                    T { text: Qt.formatTime(Sim.eta, "HH:mm"); font.pixelSize: 30 }
                }
                Column {
                    T { text: "Time"; font.pixelSize: Theme.fontSmall; color: Theme.accentMid }
                    T { text: Sim.remainingMin + " min"; font.pixelSize: 30 }
                }
                Column {
                    T { text: "Distance"; font.pixelSize: Theme.fontSmall; color: Theme.accentMid }
                    T { text: Sim.remainingKm.toFixed(1) + " km"; font.pixelSize: 30 }
                }
            }
            LineButton {
                width: parent.width
                icon: Sim.navGuidance ? Icons.pause : Icons.play
                iconSize: 24
                label: Sim.navGuidance ? "Pause simulation" : "Resume simulation"
                onClicked: Sim.navGuidance = !Sim.navGuidance
            }
        }
    }
}
