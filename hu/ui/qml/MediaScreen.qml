import QtQuick
import QtQuick.Shapes

// Now playing: cover art, track info, progress, transport controls and what comes next;
// Browse opens the source's folders, artists, albums and tracks (MediaBrowser).
Item {
    id: root
    objectName: "mediaScreen"       // run.py --screenshots opens the browser through it
    property int sel: 1          // 0 prev, 1 play/pause, 2 next, 3 browse (knob focus)
    property bool browsing: false
    readonly property var sources: Sim.mediaSources     // from hu-mediad: Library and the USB sticks

    function openBrowser() { browser.reset(); browsing = true }
    function knob(d) { if (browsing) browser.knob(d); else sel = (sel + d + 4) % 4 }
    function side(d) { if (browsing) browser.side(d); else knob(d) }
    function press() {
        if (browsing) browser.press();
        else if (sel === 0) Sim.prevTrack();
        else if (sel === 1) Sim.playing = !Sim.playing;
        else if (sel === 2) Sim.nextTrack();
        else openBrowser();
    }
    // main.qml asks before going home: in the browser, back goes up one level
    function back() { if (!browsing) return false; browser.back(); return true }

    Tabs {
        x: Theme.margin
        y: 12
        labels: root.sources
        current: Math.max(0, root.sources.indexOf(Sim.mediaSource))
        onSelected: (i) => Sim.mediaSource = root.sources[i]
    }
    LineButton {
        anchors.right: parent.right
        anchors.rightMargin: Theme.margin
        y: 12
        height: 52
        icon: Icons.list
        iconSize: 24
        label: "Browse"
        highlighted: root.sel === 3
        onClicked: { root.sel = 3; root.openBrowser() }
    }

    // cover art: the track's picture tinted in the accent colour (image://cover, live
    // only, hu/ui/covers.py); without one, the drawn sunset over water from the vision sheet
    readonly property string coverUrl: Sim.track && Sim.track.cover
        ? "image://cover/" + Theme.accent.toString().slice(1) + "/" + encodeURIComponent(Sim.track.cover) : ""
    Rectangle {
        id: cover
        x: Theme.margin
        y: 86
        width: 300; height: 300
        color: Theme.bg
        border.color: Theme.accent
        border.width: 2
        Image {
            id: coverImage
            anchors.fill: parent
            anchors.margins: 14
            source: root.coverUrl
            sourceSize.width: width
            sourceSize.height: height
            fillMode: Image.PreserveAspectFit
            asynchronous: true
            visible: status === Image.Ready
        }
        Item {
            id: art
            anchors.centerIn: parent
            width: 200; height: 200
            clip: true
            visible: coverImage.status !== Image.Ready
            Rectangle {
                width: 200; height: 200; radius: 100
                color: Theme.accent
                y: 0
            }
            // horizontal cuts through the lower half of the sun
            Repeater {
                model: 7
                Rectangle {
                    y: 104 + index * 14 + index * index * 0.6
                    width: 200
                    height: 3 + index * 1.4
                    color: Theme.bg
                }
            }
        }
        rotation: 0
    }

    T {
        // an empty source: nothing to play
        x: cover.x + cover.width + 40
        y: 96
        visible: Sim.trackCount === 0
        text: "No music on " + Sim.mediaSource
        font.pixelSize: 40
    }

    Column {
        x: cover.x + cover.width + 40
        y: 96
        visible: Sim.trackCount > 0
        width: 850 - x
        spacing: 10
        T { width: parent.width; text: Sim.track.title; font.pixelSize: 40 }
        T { width: parent.width; text: Sim.track.artist; font.pixelSize: Theme.fontLarge; color: Theme.accentMid }
        T { width: parent.width; text: Sim.track.album; font.pixelSize: Theme.fontNormal; color: Theme.accentMid }
        Item { width: 1; height: 56 }
        LineSlider {
            width: parent.width
            from: 0; to: Sim.track.duration
            value: Sim.trackPos
            onMoved: (v) => Sim.trackPos = Math.round(v)
        }
        Item {
            width: parent.width; height: 30
            T { text: Sim.fmtTime(Sim.trackPos); font.pixelSize: Theme.fontSmall }
            T { anchors.right: parent.right; text: Sim.fmtTime(Sim.track.duration); font.pixelSize: Theme.fontSmall }
        }
    }

    Row {
        x: Theme.margin + (850 - Theme.margin - width) / 2
        y: cover.y + cover.height + 70
        spacing: 44
        LineButton { round: true; icon: Icons.shuffle; iconSize: 28; highlighted: Sim.shuffle; width: 60; height: 60; anchors.verticalCenter: parent.verticalCenter; onClicked: Sim.shuffle = !Sim.shuffle }
        LineButton { round: true; icon: Icons.prev; iconSize: 32; width: 80; height: 80; highlighted: root.sel === 0; anchors.verticalCenter: parent.verticalCenter; onClicked: { root.sel = 0; Sim.prevTrack() } }
        LineButton {
            round: true; width: 110; height: 110; iconSize: 48
            icon: Sim.playing ? Icons.pause : Icons.play
            highlighted: root.sel === 1
            onClicked: { root.sel = 1; Sim.playing = !Sim.playing }
        }
        LineButton { round: true; icon: Icons.next; iconSize: 32; width: 80; height: 80; highlighted: root.sel === 2; anchors.verticalCenter: parent.verticalCenter; onClicked: { root.sel = 2; Sim.nextTrack() } }
        LineButton { round: true; icon: Icons.repeat; iconSize: 28; highlighted: Sim.repeatAll; width: 60; height: 60; anchors.verticalCenter: parent.verticalCenter; onClicked: Sim.repeatAll = !Sim.repeatAll }
    }

    // up next
    Rectangle { x: 880; y: 86; width: 1; height: 560; color: Theme.accentDim }
    Column {
        x: 910
        y: 80
        width: parent.width - x - Theme.margin
        spacing: 4
        T {
            width: parent.width
            text: "Up next" + (Sim.trackCount ? "  ·  " + Sim.queueTitle : "")
            color: Theme.accentMid; font.pixelSize: Theme.fontSmall; bottomPadding: 8
            elide: Text.ElideRight
        }
        Repeater {
            // what really comes next, in play order (shuffle included): from hu-mediad
            model: Sim.upNext
            Item {
                required property var modelData
                required property int index
                readonly property var next: modelData
                width: parent.width
                height: 104
                Row {
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 16
                    T { text: (index + 1).toString(); color: Theme.accentDim; font.family: Theme.numberFamily; font.pixelSize: 44; width: 26 }
                    Column {
                        width: 280
                        T { width: parent.width; text: next ? next.title : ""; font.pixelSize: Theme.fontSmall + 2 }
                        T { width: parent.width; text: next ? ((next.artist ? next.artist + "  ·  " : "") + Sim.fmtTime(next.duration)) : ""; color: Theme.accentMid; font.pixelSize: Theme.fontSmall - 1 }
                    }
                }
                Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.accentFaint }
                MouseArea { anchors.fill: parent; onClicked: { Sim.trackIndex = next.index; Sim.trackPos = 0; Sim.playing = true } }
            }
        }
    }

    MediaBrowser {
        id: browser
        anchors.fill: parent
        visible: root.browsing
        onDone: (played) => { root.browsing = false; if (played) root.sel = 1 }   // knob back on play/pause
    }
}
