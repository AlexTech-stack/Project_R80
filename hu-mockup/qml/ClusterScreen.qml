import QtQuick
import QtQuick.Shapes

// Drive view: speedometer, rev counter, fuel, gear - like a virtual cluster.
Item {
    id: root
    function knob(d) {}
    function press() {}

    // Generic arc gauge with ticks
    component ArcGauge: Item {
        id: g
        property real value: 0
        property real maxValue: 100
        property real startAngle: 135
        property real sweep: 270
        property real radius: 200
        property int majorTicks: 10
        property int minorPerMajor: 2
        property real lineWidth: 10
        property bool labels: true
        property real labelDivisor: 1
        width: radius * 2 + 40; height: radius * 2 + 40
        readonly property real cx: width / 2
        readonly property real cy: height / 2
        readonly property real frac: Math.min(1, Math.max(0, value / maxValue))

        Shape {
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer
            ShapePath {   // outer thin ring
                strokeColor: Theme.accentDim; strokeWidth: 2; fillColor: "transparent"
                PathAngleArc { centerX: g.cx; centerY: g.cy; radiusX: g.radius + 12; radiusY: g.radius + 12; startAngle: g.startAngle; sweepAngle: g.sweep }
            }
            ShapePath {   // value arc
                strokeColor: Theme.accent; strokeWidth: g.lineWidth; fillColor: "transparent"
                capStyle: ShapePath.FlatCap
                PathAngleArc { centerX: g.cx; centerY: g.cy; radiusX: g.radius; radiusY: g.radius; startAngle: g.startAngle; sweepAngle: g.sweep * g.frac }
            }
        }
        Repeater {
            model: g.majorTicks * g.minorPerMajor + 1
            Rectangle {
                readonly property bool major: index % g.minorPerMajor === 0
                readonly property real a: (g.startAngle + g.sweep * index / (g.majorTicks * g.minorPerMajor)) * Math.PI / 180
                readonly property real r: g.radius - g.lineWidth / 2 - 8
                width: major ? 20 : 10; height: 2
                x: g.cx + Math.cos(a) * (r - width / 2) - width / 2
                y: g.cy + Math.sin(a) * (r - width / 2) - 1
                rotation: a * 180 / Math.PI
                color: major ? Theme.accent : Theme.accentMid
            }
        }
        Repeater {
            model: g.labels ? g.majorTicks + 1 : 0
            T {
                readonly property real a: (g.startAngle + g.sweep * index / g.majorTicks) * Math.PI / 180
                readonly property real r: g.radius - g.lineWidth - 44
                x: g.cx + Math.cos(a) * r - width / 2
                y: g.cy + Math.sin(a) * r - height / 2
                text: Math.round(index * g.maxValue / g.majorTicks / g.labelDivisor)
                font.pixelSize: Theme.fontSmall
                color: Theme.accentMid
            }
        }
    }

    // speed
    ArcGauge {
        id: speedo
        anchors.centerIn: parent
        anchors.verticalCenterOffset: 6
        radius: 270
        value: Sim.speed
        maxValue: 260
        majorTicks: 13
        startAngle: 140; sweep: 260
        lineWidth: 12
        Column {
            anchors.centerIn: parent
            T { anchors.horizontalCenter: parent.horizontalCenter; text: Math.round(Sim.speed); font.family: Theme.numberFamily; font.pixelSize: 150 }
            T { anchors.horizontalCenter: parent.horizontalCenter; text: "km/h"; color: Theme.accentMid }
        }
        T {
            anchors.horizontalCenter: parent.horizontalCenter
            y: parent.height - 120
            text: Sim.gear
            font.family: Theme.numberFamily
            font.pixelSize: 64
        }
    }

    // rpm (left)
    ArcGauge {
        x: 20; anchors.verticalCenter: parent.verticalCenter
        radius: 150
        value: Sim.rpm
        maxValue: 7000
        majorTicks: 7
        startAngle: 110; sweep: 140
        lineWidth: 8
        labelDivisor: 1000
        Column {
            x: 120; anchors.verticalCenter: parent.verticalCenter
            T { text: "rpm"; font.pixelSize: Theme.fontSmall; color: Theme.accentMid }
            T { text: Math.round(Sim.rpm / 10) * 10; font.family: Theme.numberFamily; font.pixelSize: 48 }
            T { text: "x1000"; font.pixelSize: 14; color: Theme.accentDim }
        }
    }

    // fuel (right): segmented bar
    Item {
        anchors.right: parent.right; anchors.rightMargin: Theme.margin + 20
        anchors.verticalCenter: parent.verticalCenter
        width: 200; height: 420
        Column {
            anchors.right: parent.right
            spacing: 5
            Repeater {
                model: 20
                Rectangle {
                    width: 18; height: 16
                    color: (19 - index) / 20 < Sim.fuelLevel ? Theme.accent : "transparent"
                    border.color: Theme.accentDim; border.width: 1
                }
            }
        }
        Column {
            anchors.right: parent.right; anchors.rightMargin: 44
            anchors.verticalCenter: parent.verticalCenter
            spacing: 6
            Icon { anchors.right: parent.right; path: Icons.fuel; width: 40; height: 40 }
            T { anchors.right: parent.right; text: Sim.rangeKm; font.family: Theme.numberFamily; font.pixelSize: 48 }
            T { anchors.right: parent.right; text: "km range"; font.pixelSize: Theme.fontSmall; color: Theme.accentMid }
        }
    }

    // bottom info line
    T { x: Theme.margin; anchors.bottom: parent.bottom; anchors.bottomMargin: 18
        text: Math.floor(Sim.odometer) + " km"; color: Theme.accentMid; font.pixelSize: Theme.fontSmall }
    T { anchors.right: parent.right; anchors.rightMargin: Theme.margin; anchors.bottom: parent.bottom; anchors.bottomMargin: 18
        text: (Sim.outsideTemp >= 0 ? "+" : "") + Math.round(Sim.outsideTemp) + " °C"; font.pixelSize: Theme.fontNormal }
    Row {
        anchors.left: parent.left; anchors.leftMargin: Theme.margin
        anchors.top: parent.top; anchors.topMargin: 18
        spacing: 12
        Icon { path: Icons.music; width: 26; height: 26; anchors.verticalCenter: parent.verticalCenter }
        T { text: Sim.track.title + "  ·  " + Sim.track.artist; font.pixelSize: Theme.fontSmall; color: Theme.accentMid }
    }
    Row {
        anchors.right: parent.right; anchors.rightMargin: Theme.margin
        anchors.top: parent.top; anchors.topMargin: 18
        spacing: 12
        visible: Sim.navGuidance
        Icon {
            path: Sim.nextManeuver.type === "right" ? Icons.turnRight : Sim.nextManeuver.type === "left" ? Icons.turnLeft : Icons.straight
            width: 30; height: 30; anchors.verticalCenter: parent.verticalCenter
        }
        T { text: Sim.nextManeuver.km.toFixed(1) + " km  " + Sim.nextManeuver.street; font.pixelSize: Theme.fontSmall }
    }
}
