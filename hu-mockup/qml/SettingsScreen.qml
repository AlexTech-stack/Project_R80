import QtQuick

// Settings: categories on the left, the chosen page on the right.
// Display changes (brightness, accent colour) apply live to the whole UI.
Item {
    id: root
    property int cat: 1
    property int item: 0
    property bool inPanel: false
    readonly property var cats: [
        { label: "General",      icon: Icons.globe },
        { label: "Display",      icon: Icons.display },
        { label: "Audio",        icon: Icons.speaker },
        { label: "Connectivity", icon: Icons.wifi },
        { label: "System",       icon: Icons.chip }
    ]
    // local fake settings
    property int bass: 2
    property int treble: 1
    property real balance: 0
    property real fader: 0
    property bool loudness: true
    property bool bt: true
    property bool wifi: false
    property bool carplay: false
    property bool nightDim: true
    property int language: 0

    readonly property var itemCounts: [3, 3, 5, 3, 1]
    onCatChanged: item = 0

    function knob(d) {
        if (inPanel) item = (item + d + itemCounts[cat]) % itemCounts[cat];
        else cat = (cat + d + cats.length) % cats.length;
    }
    function side(d) {
        if (!inPanel) { if (d > 0) inPanel = true; return }
        if (d < 0 && item === 0 && !adjustable()) { inPanel = false; return }
        adjust(d);
    }
    function press() { if (!inPanel) inPanel = true; else adjust(1) }
    function adjustable() { return (cat === 1 && item < 2) || cat === 2 }
    function adjust(d) {
        if (cat === 0) {
            if (item === 0) language = (language + 1) % 3;
            else if (item === 1) Sim.clock24h = !Sim.clock24h;
            else Sim.units_metric = !Sim.units_metric;
        } else if (cat === 1) {
            if (item === 0) Theme.brightness = Math.min(1, Math.max(0.2, Theme.brightness + d * 0.1));
            else if (item === 1) Theme.accentIndex = (Theme.accentIndex + d + Theme.accents.length) % Theme.accents.length;
            else nightDim = !nightDim;
        } else if (cat === 2) {
            if (item === 0) Sim.volume = Math.min(30, Math.max(0, Sim.volume + d));
            else if (item === 1) bass = Math.min(6, Math.max(-6, bass + d));
            else if (item === 2) treble = Math.min(6, Math.max(-6, treble + d));
            else if (item === 3) balance = Math.min(1, Math.max(-1, balance + d * 0.2));
            else loudness = !loudness;
        } else if (cat === 3) {
            if (item === 0) bt = !bt; else if (item === 1) wifi = !wifi; else carplay = !carplay;
        }
    }

    Column {
        id: menu
        x: Theme.margin
        y: 22
        width: 400
        spacing: 11
        Repeater {
            model: root.cats
            MenuRow {
                width: menu.width
                height: 64
                icon: modelData.icon
                label: modelData.label
                selected: index === root.cat
                opacity: root.inPanel && index !== root.cat ? 0.6 : 1
                chevron: true
                onClicked: { root.cat = index; root.inPanel = false }
            }
        }
    }
    Rectangle { x: menu.x + menu.width + 36; y: 30; width: 1; height: parent.height - 60; color: Theme.accentDim }

    component SettingRow: Item {
        id: sr
        property string label
        property int idx
        default property alias control: holder.data
        width: 700; height: 84
        readonly property bool focused: root.inPanel && root.item === idx
        Rectangle { anchors.fill: parent; color: Theme.accentFaint; visible: sr.focused; border.color: Theme.accentDim }
        T { x: 18; text: sr.label; anchors.verticalCenter: parent.verticalCenter }
        Item { id: holder; x: 300; width: 380; height: parent.height }
        MouseArea { anchors.fill: parent; z: -1; onClicked: { root.inPanel = true; root.item = sr.idx } }
    }

    Item {
        id: panel
        x: menu.x + menu.width + 76
        y: 22
        width: parent.width - x - Theme.margin
        height: parent.height - 44

        // General
        Column {
            visible: root.cat === 0
            spacing: 8
            SettingRow { label: "Language"; idx: 0
                T { anchors.verticalCenter: parent.verticalCenter; text: ["English", "Deutsch", "Français"][root.language] }
                MouseArea { anchors.fill: parent; onClicked: { root.inPanel = true; root.item = 0; root.adjust(1) } } }
            SettingRow { label: "24-hour clock"; idx: 1
                Toggle { anchors.verticalCenter: parent.verticalCenter; checked: Sim.clock24h; onToggled: Sim.clock24h = !Sim.clock24h } }
            SettingRow { label: "Metric units"; idx: 2
                Toggle { anchors.verticalCenter: parent.verticalCenter; checked: Sim.units_metric; onToggled: Sim.units_metric = !Sim.units_metric } }
        }

        // Display
        Column {
            visible: root.cat === 1
            spacing: 8
            Item {
                width: 700; height: 120
                Icon { anchors.horizontalCenter: parent.horizontalCenter; path: Icons.brightness; width: 90; height: 90; stroke: 1.3 }
            }
            SettingRow { label: "Brightness"; idx: 0
                LineSlider { anchors.verticalCenter: parent.verticalCenter; width: 360; from: 0.2; to: 1; value: Theme.brightness
                             focused: root.inPanel && root.item === 0; onMoved: (v) => Theme.brightness = v } }
            SettingRow { label: "Accent colour"; idx: 1
                Row {
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 18
                    Repeater {
                        model: Theme.accents
                        Rectangle {
                            width: 50; height: 50; radius: 25
                            color: modelData.color
                            border.color: index === Theme.accentIndex ? "white" : "transparent"
                            border.width: 3
                            MouseArea { anchors.fill: parent; onClicked: Theme.accentIndex = index }
                        }
                    }
                }
            }
            SettingRow { label: "Dim at night"; idx: 2
                Toggle { anchors.verticalCenter: parent.verticalCenter; checked: root.nightDim; onToggled: root.nightDim = !root.nightDim } }
            T { x: 18; text: Theme.accents[Theme.accentIndex].name; color: Theme.accentMid; font.pixelSize: Theme.fontSmall }
        }

        // Audio
        Column {
            visible: root.cat === 2
            spacing: 6
            SettingRow { label: "Volume  " + Sim.volume; idx: 0
                LineSlider { anchors.verticalCenter: parent.verticalCenter; width: 360; from: 0; to: 30; value: Sim.volume
                             focused: root.inPanel && root.item === 0; onMoved: (v) => Sim.volume = Math.round(v) } }
            SettingRow { label: "Bass  " + (root.bass > 0 ? "+" : "") + root.bass; idx: 1
                LineSlider { anchors.verticalCenter: parent.verticalCenter; width: 360; from: -6; to: 6; value: root.bass; centered: true
                             focused: root.inPanel && root.item === 1; onMoved: (v) => root.bass = Math.round(v) } }
            SettingRow { label: "Treble  " + (root.treble > 0 ? "+" : "") + root.treble; idx: 2
                LineSlider { anchors.verticalCenter: parent.verticalCenter; width: 360; from: -6; to: 6; value: root.treble; centered: true
                             focused: root.inPanel && root.item === 2; onMoved: (v) => root.treble = Math.round(v) } }
            SettingRow { label: "Balance"; idx: 3
                LineSlider { anchors.verticalCenter: parent.verticalCenter; width: 360; from: -1; to: 1; value: root.balance; centered: true
                             focused: root.inPanel && root.item === 3; onMoved: (v) => root.balance = v } }
            SettingRow { label: "Loudness"; idx: 4
                Toggle { anchors.verticalCenter: parent.verticalCenter; checked: root.loudness; onToggled: root.loudness = !root.loudness } }
        }

        // Connectivity
        Column {
            visible: root.cat === 3
            spacing: 8
            SettingRow { label: "Bluetooth"; idx: 0
                Toggle { anchors.verticalCenter: parent.verticalCenter; checked: root.bt; onToggled: root.bt = !root.bt } }
            SettingRow { label: "Wi-Fi hotspot"; idx: 1
                Toggle { anchors.verticalCenter: parent.verticalCenter; checked: root.wifi; onToggled: root.wifi = !root.wifi } }
            SettingRow { label: "Phone projection"; idx: 2
                Toggle { anchors.verticalCenter: parent.verticalCenter; checked: root.carplay; onToggled: root.carplay = !root.carplay } }
            Item { width: 1; height: 20 }
            T { x: 18; text: "Paired devices"; color: Theme.accentMid; font.pixelSize: Theme.fontSmall }
            Repeater {
                model: [Sim.phoneName + "  (connected)", "Workshop tablet", "OBD dongle"]
                Row {
                    x: 18; spacing: 14
                    Icon { path: Icons.bluetooth; width: 26; height: 26; color: index === 0 ? Theme.accent : Theme.accentDim }
                    T { text: modelData; font.pixelSize: Theme.fontSmall + 2; color: index === 0 ? Theme.accent : Theme.accentMid }
                }
            }
        }

        // System
        Column {
            visible: root.cat === 4
            spacing: 14
            x: 18
            Logo { width: 150; height: 46 }
            Item { width: 1; height: 10 }
            T { text: "R80 Headunit  -  UI mockup v0.3" }
            T { text: "Qt " + "6 / QML  ·  simulated data"; color: Theme.accentMid; font.pixelSize: Theme.fontSmall }
            T { text: "Display 1280 x 768 (5:3)"; color: Theme.accentMid; font.pixelSize: Theme.fontSmall }
            T { text: "Fonts: B612 (OFL/EPL), OSP-DIN (OFL)"; color: Theme.accentMid; font.pixelSize: Theme.fontSmall }
            T { text: "Icons & line art: drawn for this project"; color: Theme.accentMid; font.pixelSize: Theme.fontSmall }
            Item { width: 1; height: 16 }
            SettingRow { label: "Simulate incoming call"; idx: 0; x: -18
                LineButton { anchors.verticalCenter: parent.verticalCenter; icon: Icons.phone; label: "Ring"; iconSize: 22; onClicked: Sim.simulateIncomingCall() } }
        }
    }
}
