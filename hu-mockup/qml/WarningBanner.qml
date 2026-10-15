import QtQuick

// Vehicle warning banner below the header (D10). Shows the most urgent unacknowledged
// "warning" (filled) or "information" (outlined) until the driver acknowledges it with
// OK or a knob press; a new "notice" is shown for a few seconds only (silent, not dangerous).
// While a banner is up the knob goes to it; touch on the rest of the screen still works.
Item {
    id: root
    anchors.fill: parent
    readonly property var pending: Sim.warnings.filter(w => !w.acknowledged && w.severity !== "notice")
    readonly property var current: pending.length ? pending[0] : null
    property var notice: null                  // a notice being shown briefly
    property var seenNotices: ({})
    readonly property var shown: current || notice
    readonly property bool active: current !== null
    visible: shown !== null

    function press() { if (current) Sim.acknowledgeWarning(current.id) }
    function knob(d) {}
    function side(d) {}

    Connections {
        target: Sim
        function onWarningsChanged() {
            const now = {}
            for (const w of Sim.warnings) {
                if (w.severity !== "notice") continue
                now[w.id] = true
                if (!root.seenNotices[w.id]) { root.notice = w; noticeTimer.restart() }
            }
            root.seenNotices = now                 // a notice that clears shows again next time
            if (root.notice && !now[root.notice.id]) root.notice = null
        }
    }
    Timer { id: noticeTimer; interval: 5000; onTriggered: root.notice = null }

    Rectangle {
        id: panel
        readonly property bool urgent: root.shown && root.shown.severity === "warning"
        x: Theme.margin
        y: Theme.headerHeight + 10
        width: parent.width - 2 * Theme.margin
        height: 104
        radius: 3
        color: urgent ? Theme.accent : Theme.bg
        border.color: root.shown && root.shown.severity === "notice" ? Theme.accentDim : Theme.accent
        border.width: 2
        MouseArea { anchors.fill: parent }    // the banner itself takes the touch

        Icon {
            x: 26; anchors.verticalCenter: parent.verticalCenter
            width: 50; height: 50; stroke: 1.8
            path: root.shown && root.shown.severity === "warning" ? Icons.warning : Icons.info
            color: panel.urgent ? Theme.textOnAccent : Theme.accent
        }
        Column {
            x: 100; anchors.verticalCenter: parent.verticalCenter
            width: parent.width - 100 - 260
            spacing: 4
            T {
                text: !root.shown ? "" : root.shown.severity === "warning" ? "Warning"
                      : root.shown.severity === "information" ? "Information" : "Notice"
                font.pixelSize: Theme.fontSmall
                color: panel.urgent ? Theme.textOnAccent : Theme.accentMid
            }
            T {
                width: parent.width
                text: root.shown ? root.shown.text : ""
                font.pixelSize: Theme.fontLarge
                elide: Text.ElideRight
                color: panel.urgent ? Theme.textOnAccent : Theme.accent
            }
        }
        T {
            anchors.right: ok.left; anchors.rightMargin: 24; anchors.verticalCenter: parent.verticalCenter
            visible: root.pending.length > 1
            text: "+" + (root.pending.length - 1) + " more"
            font.pixelSize: Theme.fontSmall
            color: panel.urgent ? Theme.textOnAccent : Theme.accentMid
        }
        Rectangle { anchors.fill: ok; radius: 3; color: Theme.bg; visible: ok.visible && panel.urgent }
        LineButton {
            id: ok
            anchors.right: parent.right; anchors.rightMargin: 24; anchors.verticalCenter: parent.verticalCenter
            visible: root.current !== null
            label: "OK"
            highlighted: !panel.urgent
            onClicked: root.press()
        }
    }
}
