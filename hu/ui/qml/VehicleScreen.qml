import QtQuick

// Vehicle data: status, trip computer, tyres, service, active warnings (D10).
Item {
    id: root
    objectName: "vehicleScreen"     // run.py --screenshots opens the Warnings tab through it
    property int tab: 0
    readonly property var tabs: ["Status", "Trip", "Tyres", "Service", "Warnings"]
    readonly property int warningsTab: 4
    function knob(d) { tab = (tab + d + tabs.length) % tabs.length }
    function press() {}

    Tabs {
        x: Theme.margin
        y: 12
        labels: root.tabs
        current: root.tab
        onSelected: (i) => root.tab = i
    }

    component DataRow: Item {
        property string icon
        property string label
        property string value
        property bool warn: false
        width: 480; height: 66
        Icon { path: parent.icon; width: 34; height: 34; anchors.verticalCenter: parent.verticalCenter }
        T { x: 58; text: parent.label; anchors.verticalCenter: parent.verticalCenter }
        T { anchors.right: parent.right; text: parent.value; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: Theme.fontLarge }
        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.accentFaint }
    }

    // --- Status
    Item {
        anchors.fill: parent
        visible: root.tab === 0
        CarSide { x: Theme.margin - 10; y: 120; width: 680; height: 231; stroke: 1.2 }
        T {
            x: Theme.margin; y: 420
            text: "Odometer  " + (Fmt.known(Sim.odometer) ? Math.floor(Sim.odometer).toLocaleString(Qt.locale("de_DE"), 'f', 0) : "–") + " km"
            color: Theme.accentMid
        }
        Column {
            x: 740; y: 90
            DataRow { icon: Icons.oil;     label: "Oil temp";   value: Fmt.num(Sim.oilTemp, 0, "°C") }
            DataRow { icon: Icons.coolant; label: "Coolant";    value: Fmt.num(Sim.coolantTemp, 0, "°C") }
            DataRow { icon: Icons.battery; label: "Battery";    value: Fmt.num(Sim.batteryVolt, 1, "V") }
            DataRow { icon: Icons.fuel;    label: "Fuel range"; value: Fmt.num(Sim.rangeKm, 0, "km") }
            DataRow { icon: Icons.fuel;    label: "Fuel level"; value: Fmt.num(Sim.fuelLevel * 55, 0) + " / 55 l" }
            DataRow { icon: Icons.sun;     label: "Outside";    value: Fmt.num(Sim.outsideTemp, 0, "°C") }
        }
    }

    // --- Trip (D10): "since start" (starts over after 2 h with the ignition off) and long-term
    Row {
        visible: root.tab === 1
        x: Theme.margin; y: 84
        spacing: 60
        Repeater {
            model: [{ title: "Since start", which: "start", t: Sim.tripStart },
                    { title: "Long-term", which: "long", t: Sim.tripLong }]
            Column {
                width: (root.width - 2 * Theme.margin - 60) / 2
                spacing: 2
                Item {
                    width: parent.width; height: 64
                    T { text: modelData.title; font.pixelSize: Theme.fontLarge; anchors.verticalCenter: parent.verticalCenter }
                    LineButton {
                        anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                        label: "Reset"
                        onClicked: Sim.resetTrip(modelData.which)
                    }
                }
                Repeater {
                    model: [
                        { label: "Distance",         value: Fmt.num(modelData.t.km, 1).replace(".", ","), unit: "km" },
                        { label: "Driving time",     value: Fmt.known(modelData.t.minutes) ? Math.floor(modelData.t.minutes / 60) + ":" + ("0" + modelData.t.minutes % 60).slice(-2) : "–", unit: "h" },
                        { label: "Avg. speed",       value: Fmt.num(modelData.t.avgSpeed, 0), unit: "km/h" },
                        { label: "Max. speed",       value: Fmt.num(modelData.t.maxSpeed, 0), unit: "km/h" },
                        { label: "Avg. consumption", value: Fmt.num(Sim.avgConsumption, 1).replace(".", ","), unit: "l/100 km" }
                    ]
                    Item {
                        width: parent.width; height: 100
                        T { y: 8; text: modelData.label; color: Theme.accentMid; font.pixelSize: Theme.fontSmall }
                        Row {
                            y: 32; spacing: 10
                            T { id: big; text: modelData.value; font.family: Theme.numberFamily; font.pixelSize: 52 }
                            T { text: modelData.unit; font.pixelSize: Theme.fontNormal; anchors.baseline: big.baseline; color: Theme.accentMid }
                        }
                        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.accentFaint }
                    }
                }
            }
        }
    }

    // --- Tyres (top view)
    Item {
        visible: root.tab === 2
        anchors.fill: parent
        Rectangle {
            id: body
            width: 200; height: 440
            anchors.centerIn: parent; anchors.verticalCenterOffset: 30
            radius: 60
            color: "transparent"; border.color: Theme.accent; border.width: 2
            Rectangle { x: 26; y: 110; width: 148; height: 90; radius: 16; color: "transparent"; border.color: Theme.accentMid; border.width: 1.5 }
            Rectangle { x: 26; y: 300; width: 148; height: 60; radius: 14; color: "transparent"; border.color: Theme.accentMid; border.width: 1.5 }
        }
        Repeater {
            model: 4
            Item {
                readonly property bool isRight: index % 2 === 1
                readonly property bool isRear: index >= 2
                x: body.x + (isRight ? body.width - 10 : -24)
                y: body.y + (isRear ? 300 : 60)
                Rectangle { width: 34; height: 84; radius: 8; color: "transparent"; border.color: Theme.accent; border.width: 2 }
                Column {
                    x: parent.isRight ? 70 : -200
                    y: 6
                    width: 160
                    T { width: parent.width; horizontalAlignment: parent.parent.isRight ? Text.AlignLeft : Text.AlignRight
                        text: Fmt.num(Sim.tyres[index], 1, "bar"); font.pixelSize: 38; font.family: Theme.numberFamily }
                    T { width: parent.width; horizontalAlignment: parent.parent.isRight ? Text.AlignLeft : Text.AlignRight
                        text: ["Front left", "Front right", "Rear left", "Rear right"][index]; color: Theme.accentMid; font.pixelSize: Theme.fontSmall }
                }
            }
        }
    }

    // --- Service
    Column {
        visible: root.tab === 3
        x: Theme.margin + 40; y: 130
        spacing: 30
        Row {
            spacing: 28
            Icon { path: Icons.oil; width: 64; height: 64 }
            Column {
                T { text: "Oil change due in"; color: Theme.accentMid }
                T { text: (Fmt.known(Sim.serviceKm) ? Sim.serviceKm.toLocaleString(Qt.locale("de_DE"), 'f', 0) : "–") + " km  /  " + Fmt.num(Sim.serviceDays, 0) + " days"; font.pixelSize: 44 }
            }
        }
        Row {
            spacing: 28
            Icon { path: Icons.wrench; width: 64; height: 64 }
            Column {
                T { text: "Inspection due in"; color: Theme.accentMid }
                T { text: "18.600 km  /  301 days"; font.pixelSize: 44 }
            }
        }
        Row {
            spacing: 28
            Icon { path: Icons.chip; width: 64; height: 64 }
            Column {
                T { text: "Fault memory"; color: Theme.accentMid }
                T { text: "No entries"; font.pixelSize: 44 }
            }
        }
    }

    // --- Warnings (D10): everything hu-warnd reports, most urgent first
    Item {
        anchors.fill: parent
        visible: root.tab === root.warningsTab
        T {
            x: Theme.margin; y: 110
            visible: Sim.warnings.length === 0
            text: "No warnings"
            color: Theme.accentMid
        }
        Column {
            x: Theme.margin; y: 84
            width: parent.width - 2 * Theme.margin
            Repeater {
                model: Sim.warnings
                Item {
                    width: parent.width; height: 74
                    Icon {
                        anchors.verticalCenter: parent.verticalCenter
                        width: 34; height: 34
                        path: modelData.severity === "warning" ? Icons.warning : Icons.info
                        color: modelData.severity === "notice" ? Theme.accentMid : Theme.accent
                    }
                    T {
                        x: 58; width: parent.width - 58 - 360; anchors.verticalCenter: parent.verticalCenter
                        text: modelData.text; elide: Text.ElideRight
                        color: modelData.severity === "notice" ? Theme.accentMid : Theme.accent
                    }
                    T {
                        anchors.right: parent.right; anchors.rightMargin: 150; anchors.verticalCenter: parent.verticalCenter
                        text: modelData.severity === "warning" ? "Warning" : modelData.severity === "information" ? "Information" : "Notice"
                        font.pixelSize: Theme.fontSmall; color: Theme.accentMid
                    }
                    T {
                        anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                        text: modelData.acknowledged ? "acknowledged" : modelData.severity === "notice" ? "" : "open"
                        font.pixelSize: Theme.fontSmall
                        color: modelData.acknowledged ? Theme.accentDim : Theme.accent
                    }
                    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.accentFaint }
                }
            }
        }
    }
}
