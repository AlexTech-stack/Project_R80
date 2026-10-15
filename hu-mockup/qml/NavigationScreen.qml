import QtQuick

// Turn-by-turn guidance from the phone (D11): the phone's navigation app routes,
// the R80 Companion app sends its guidance, the HU shows it here in its own style.
Item {
    id: root

    readonly property var g: Sim.guidance
    readonly property var phone: Sim.navPhone
    readonly property var dist: Fmt.distance(g.distance)
    readonly property string sourceName: ({ google_maps: "Google Maps", osmand: "OsmAnd" })[g.source] || g.source

    // ---- guidance panel ---------------------------------------------------
    Item {
        id: panel
        x: Theme.margin
        y: 18
        width: 820
        height: parent.height - 36

        Rectangle {
            anchors.fill: parent
            color: "transparent"
            border.color: Theme.accentDim
            border.width: 1
        }

        // next maneuver
        Item {
            anchors.fill: parent
            visible: root.g.active
            opacity: root.g.stale ? 0.4 : 1

            ManeuverIcon {
                id: arrow
                x: 40
                anchors.verticalCenter: parent.verticalCenter
                anchors.verticalCenterOffset: -20
                width: 320; height: 320
                maneuver: root.g.maneuver
                modifier: root.g.modifier
                exit: root.g.exit
            }
            Column {
                x: arrow.x + arrow.width + 40
                anchors.verticalCenter: arrow.verticalCenter
                width: panel.width - x - 36
                spacing: 10
                Row {
                    visible: root.dist !== null
                    spacing: 10
                    T {
                        id: distValue
                        text: root.dist ? root.dist.value : ""
                        font.family: Theme.numberFamily
                        font.pixelSize: 132
                    }
                    T {
                        text: root.dist ? root.dist.unit : ""
                        font.pixelSize: 40
                        anchors.baseline: distValue.baseline
                    }
                }
                T {
                    width: parent.width
                    text: root.g.street
                    visible: text !== ""
                    font.pixelSize: 40
                    wrapMode: Text.WordWrap
                    maximumLineCount: 2
                }
                T {
                    width: parent.width
                    text: root.g.text
                    visible: text !== "" && (root.g.maneuver === "unknown" || root.g.street === "")
                    color: Theme.accentMid
                    font.pixelSize: Theme.fontLarge
                    wrapMode: Text.WordWrap
                    maximumLineCount: 3
                }
            }
        }

        // phone link lost: the last instruction stays, dimmed
        Row {
            visible: root.g.active && root.g.stale
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 30
            spacing: 14
            Icon { path: Icons.phone; width: 34; height: 34; anchors.verticalCenter: parent.verticalCenter }
            T { text: "Phone connection lost · last instruction"; font.pixelSize: Theme.fontLarge }
        }

        // no guidance: what to do
        Column {
            visible: !root.g.active
            anchors.centerIn: parent
            spacing: 18
            Icon {
                anchors.horizontalCenter: parent.horizontalCenter
                width: 120; height: 120
                stroke: 1.2
                path: root.phone.connected ? Icons.nav : Icons.phone
            }
            T {
                anchors.horizontalCenter: parent.horizontalCenter
                text: root.phone.connected ? "Start a route on your phone" : "No phone connected"
                font.pixelSize: 40
            }
            T {
                anchors.horizontalCenter: parent.horizontalCenter
                horizontalAlignment: Text.AlignHCenter
                text: root.phone.connected ? "The guidance from Google Maps or OsmAnd appears here."
                                           : "Open the R80 Companion app on your phone."
                color: Theme.accentMid
                font.pixelSize: Theme.fontNormal
            }
        }
    }

    // ---- trip panel -------------------------------------------------------
    Item {
        x: panel.x + panel.width + 30
        y: 18
        width: parent.width - x - Theme.margin
        height: panel.height

        Column {
            width: parent.width
            spacing: 26
            visible: root.g.active
            opacity: root.g.stale ? 0.4 : 1
            Repeater {
                model: [
                    { label: "Arrival", value: root.g.arrival ? Qt.formatTime(root.g.arrival, "HH:mm") : "--:--" },
                    { label: "Time", value: Fmt.duration(root.g.remainingS) },
                    { label: "Distance", value: Fmt.distanceText(root.g.remainingM) }
                ]
                Column {
                    spacing: 2
                    T { text: modelData.label; font.pixelSize: Theme.fontSmall; color: Theme.accentMid }
                    T { text: modelData.value; font.family: Theme.numberFamily; font.pixelSize: 56 }
                }
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
                Icon { path: Icons.phone; width: 28; height: 28; anchors.verticalCenter: parent.verticalCenter }
                Column {
                    anchors.verticalCenter: parent.verticalCenter
                    T {
                        width: 300
                        text: root.phone.connected ? (root.phone.device || "Phone") : "Not connected"
                        font.pixelSize: Theme.fontSmall
                    }
                    T {
                        width: 300
                        visible: root.g.active && root.sourceName !== ""
                        text: "Route from " + root.sourceName
                        font.pixelSize: Theme.fontSmall
                        color: Theme.accentMid
                    }
                }
            }
        }
    }
}
