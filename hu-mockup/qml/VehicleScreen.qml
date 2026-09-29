import QtQuick

// Vehicle data: status, trip computer, tyres, service.
Item {
    id: root
    property int tab: 0
    readonly property var tabs: ["Status", "Trip", "Tyres", "Service"]
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
            text: "Odometer  " + Math.floor(Sim.odometer).toLocaleString(Qt.locale("de_DE"), 'f', 0) + " km"
            color: Theme.accentMid
        }
        Column {
            x: 740; y: 90
            DataRow { icon: Icons.oil;     label: "Oil temp";   value: Sim.oilTemp + " °C" }
            DataRow { icon: Icons.coolant; label: "Coolant";    value: Sim.coolantTemp + " °C" }
            DataRow { icon: Icons.battery; label: "Battery";    value: Sim.batteryVolt.toFixed(1) + " V" }
            DataRow { icon: Icons.fuel;    label: "Fuel range"; value: Sim.rangeKm + " km" }
            DataRow { icon: Icons.fuel;    label: "Fuel level"; value: Math.round(Sim.fuelLevel * 55) + " / 55 l" }
            DataRow { icon: Icons.sun;     label: "Outside";    value: Math.round(Sim.outsideTemp) + " °C" }
        }
    }

    // --- Trip
    Grid {
        visible: root.tab === 1
        x: Theme.margin + 40; y: 130
        columns: 2
        columnSpacing: 160
        rowSpacing: 50
        Repeater {
            model: [
                { label: "Distance",          value: Sim.tripKm.toFixed(1), unit: "km" },
                { label: "Driving time",      value: Math.floor(Sim.tripMinutes / 60) + ":" + ("0" + Sim.tripMinutes % 60).slice(-2), unit: "h" },
                { label: "Avg. consumption",  value: Sim.avgConsumption.toFixed(1).replace(".", ","), unit: "l/100 km" },
                { label: "Avg. speed",        value: Sim.avgSpeed, unit: "km/h" }
            ]
            Column {
                width: 440
                spacing: 4
                T { text: modelData.label; color: Theme.accentMid }
                Row {
                    spacing: 12
                    T { id: big; text: modelData.value; font.family: Theme.numberFamily; font.pixelSize: 96 }
                    T { text: modelData.unit; font.pixelSize: Theme.fontLarge; anchors.baseline: big.baseline }
                }
            }
        }
    }
    LineButton {
        visible: root.tab === 1
        anchors.right: parent.right; anchors.rightMargin: Theme.margin
        anchors.bottom: parent.bottom; anchors.bottomMargin: 30
        label: "Reset trip"
        onClicked: { Sim.tripKm = 0; Sim.tripMinutes = 0 }
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
                        text: Sim.tyres[index].toFixed(1) + " bar"; font.pixelSize: 38; font.family: Theme.numberFamily }
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
                T { text: Sim.serviceKm.toLocaleString(Qt.locale("de_DE"), 'f', 0) + " km  /  " + Sim.serviceDays + " days"; font.pixelSize: 44 }
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
}
