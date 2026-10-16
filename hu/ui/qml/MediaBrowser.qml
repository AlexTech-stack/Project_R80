import QtQuick

// Browse the source: folders, artists, albums, all tracks (hu/services/browse.py).
// Knob turns through the list, a push opens a list or plays from a track (that list
// becomes the queue), back goes up one level; Sim.browse answers in pages.
Item {
    id: root
    property var stack: []          // [{ path, title, sel }] of the lists above this one
    property string path: ""
    property string title: ""
    property int total: 0
    property var entries: []
    property int sel: 0
    property bool loading: false
    readonly property int pageSize: 60
    signal done(bool played)        // a track plays (true) or back left the top (false): close

    function open(p) {
        if (path !== "" || stack.length || entries.length)
            stack = stack.concat([{ path: path, title: title, sel: sel }])
        load(p, 0)
    }
    function reset() { stack = []; entries = []; path = ""; title = ""; total = 0; load("", 0) }
    function load(p, s) {
        path = p; sel = s; entries = []; total = 0; loading = true
        Sim.browse(p, 0, pageSize)
    }
    function back() {
        if (!stack.length) { done(false); return }
        const up = stack[stack.length - 1]
        stack = stack.slice(0, -1)
        load(up.path, up.sel)
    }
    function knob(d) {
        if (!entries.length) return
        sel = Math.max(0, Math.min(entries.length - 1, sel + d))
        list.positionViewAtIndex(sel, ListView.Contain)
        if (sel > entries.length - 10 && entries.length < total && !loading) {
            loading = true
            Sim.browse(path, entries.length, pageSize)
        }
    }
    function side(d) { knob(d * 6) }
    function press() {
        const e = entries[sel]
        if (!e) return
        if (e.kind === "track") { Sim.playFrom(path, e.index); done(true) }
        else open(e.id)
    }

    Connections {
        target: Sim
        function onBrowsed(p, offset, t, n, page) {
            if (p !== root.path) return
            root.loading = false
            if (n < 0) { root.back(); return }       // the list is gone (stick pulled, ...)
            root.title = t
            root.total = n
            root.entries = offset === 0 ? page : root.entries.concat(page)
            if (offset === 0) {
                root.sel = Math.min(root.sel, Math.max(0, page.length - 1))
                list.positionViewAtIndex(root.sel, ListView.Contain)
            }
        }
    }

    Rectangle { anchors.fill: parent; color: Theme.bg }

    // where we are
    Item {
        id: head
        x: Theme.margin
        width: parent.width - 2 * Theme.margin
        height: 64
        Icon {
            id: backIcon
            path: Icons.back
            width: 28; height: 28
            anchors.verticalCenter: parent.verticalCenter
        }
        T {
            anchors.left: backIcon.right
            anchors.leftMargin: 14
            anchors.right: count.left
            anchors.rightMargin: 20
            anchors.verticalCenter: parent.verticalCenter
            text: root.stack.map(s => s.title).concat([root.title]).filter(x => x).join("  ›  ")
            font.pixelSize: Theme.fontLarge
            elide: Text.ElideLeft
        }
        T {
            id: count
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            text: root.loading && !root.entries.length ? "…" : root.total + (root.total === 1 ? " entry" : " entries")
            color: Theme.accentMid
            font.pixelSize: Theme.fontSmall
        }
        MouseArea { anchors.fill: parent; onClicked: root.back() }
        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.accentDim }
    }

    ListView {
        id: list
        x: Theme.margin
        y: head.height + 8
        width: parent.width - 2 * Theme.margin
        height: parent.height - y
        clip: true
        model: root.entries
        boundsBehavior: Flickable.StopAtBounds
        delegate: Item {
            id: row
            required property var modelData
            required property int index
            readonly property bool selected: index === root.sel
            readonly property bool isList: modelData.kind !== "track"
            readonly property color ink: selected ? Theme.textOnAccent : Theme.accent
            width: list.width
            height: 72
            Rectangle {
                anchors.fill: parent
                color: Theme.accent
                opacity: row.selected ? 0.92 : (mouse.pressed ? 0.25 : 0)
            }
            Icon {
                id: kindIcon
                x: 14
                anchors.verticalCenter: parent.verticalCenter
                width: 32; height: 32
                color: row.ink
                path: ({ menu: ({ folders: Icons.folder, artists: Icons.person, albums: Icons.disc, tracks: Icons.list })[row.modelData.id] || Icons.list,
                         folder: Icons.folder, artist: Icons.person, album: Icons.disc, track: Icons.music })[row.modelData.kind]
            }
            Column {
                anchors.left: kindIcon.right
                anchors.leftMargin: 20
                anchors.right: value.left
                anchors.rightMargin: 20
                anchors.verticalCenter: parent.verticalCenter
                T { width: parent.width; text: row.modelData.title; color: row.ink; elide: Text.ElideRight }
                T {
                    width: parent.width
                    visible: text !== ""
                    text: row.modelData.subtitle
                    color: row.selected ? Theme.textOnAccent : Theme.accentMid
                    font.pixelSize: Theme.fontSmall
                    elide: Text.ElideRight
                }
            }
            T {
                id: value
                anchors.right: parent.right
                anchors.rightMargin: row.isList ? 48 : 14
                anchors.verticalCenter: parent.verticalCenter
                text: row.isList ? "" : Sim.fmtTime(row.modelData.duration)
                color: row.selected ? Theme.textOnAccent : Theme.accentMid
                font.pixelSize: Theme.fontSmall
            }
            Icon {
                visible: row.isList
                path: Icons.chevronRight
                width: 24; height: 24
                anchors.right: parent.right
                anchors.rightMargin: 12
                anchors.verticalCenter: parent.verticalCenter
                color: row.selected ? Theme.textOnAccent : Theme.accentMid
            }
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.accentFaint }
            MouseArea { id: mouse; anchors.fill: parent; onClicked: { root.sel = row.index; root.press() } }
        }
    }

    T {
        anchors.centerIn: list
        visible: !root.loading && root.total === 0
        text: "Nothing here"
        color: Theme.accentMid
    }
}
