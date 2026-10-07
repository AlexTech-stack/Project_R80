import QtQuick
import QtQuick.Shapes

// Now playing: cover art, track info, progress, transport controls and queue.
Item {
    id: root
    property int sel: 1          // 0 prev, 1 play/pause, 2 next (knob focus)
    readonly property var sources: ["USB", "Bluetooth", "SD card"]

    function knob(d) { sel = (sel + d + 3) % 3 }
    function side(d) { knob(d) }
    function press() {
        if (sel === 0) Sim.prevTrack();
        else if (sel === 1) Sim.playing = !Sim.playing;
        else Sim.nextTrack();
    }

    Tabs {
        x: Theme.margin
        y: 12
        labels: root.sources
        current: Math.max(0, root.sources.indexOf(Sim.mediaSource))
        onSelected: (i) => Sim.mediaSource = root.sources[i]
    }

    // cover art (drawn: sunset over water, like the vision sheet)
    Rectangle {
        id: cover
        x: Theme.margin
        y: 86
        width: 300; height: 300
        color: Theme.bg
        border.color: Theme.accent
        border.width: 2
        Item {
            id: art
            anchors.centerIn: parent
            width: 200; height: 200
            clip: true
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

    Column {
        x: cover.x + cover.width + 40
        y: 96
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

    T {
        x: Theme.margin
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 22
        text: "Volume " + Sim.volume
        color: Theme.accentMid
        font.pixelSize: Theme.fontSmall
    }

    // up next
    Rectangle { x: 880; y: 86; width: 1; height: 560; color: Theme.accentDim }
    Column {
        x: 910
        y: 80
        width: parent.width - x - Theme.margin
        spacing: 4
        T { text: "Up next"; color: Theme.accentMid; font.pixelSize: Theme.fontSmall; bottomPadding: 8 }
        Repeater {
            model: 5
            Item {
                readonly property int ti: Sim.tracks.length ? (Sim.trackIndex + 1 + index) % Sim.tracks.length : 0
                readonly property var next: Sim.tracks.length ? Sim.tracks[ti] : null
                width: parent.width
                height: 104
                Row {
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 16
                    T { text: (index + 1).toString(); color: Theme.accentDim; font.family: Theme.numberFamily; font.pixelSize: 44; width: 26 }
                    Column {
                        width: 280
                        T { width: parent.width; text: next ? next.title : ""; font.pixelSize: Theme.fontSmall + 2 }
                        T { width: parent.width; text: next ? (next.artist + "  ·  " + Sim.fmtTime(next.duration)) : ""; color: Theme.accentMid; font.pixelSize: Theme.fontSmall - 1 }
                    }
                }
                Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.accentFaint }
                MouseArea { anchors.fill: parent; onClicked: { Sim.trackIndex = ti; Sim.trackPos = 0; Sim.playing = true } }
            }
        }
    }
}
