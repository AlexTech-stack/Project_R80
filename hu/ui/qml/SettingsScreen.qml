import QtQuick

// Settings: categories on the left, the chosen page on the right. Every value goes through
// Sim.setSetting (kept and saved by hu-sysd, D12) or Sim.setTone (hu-audiod, D9) and applies
// live to the whole UI.
Item {
    id: root
    objectName: "settingsScreen"     // run.py --screenshots opens the Audio page through it
    property int cat: 1
    property int item: 0
    property bool inPanel: false
    readonly property var cats: [
        { label: "General",      icon: Icons.globe },
        { label: "Display",      icon: Icons.display },
        { label: "Audio",        icon: Icons.speaker },
        { label: "Phone",        icon: Icons.phone },
        { label: "Connectivity", icon: Icons.wifi },
        { label: "System",       icon: Icons.chip }
    ]
    // not wired yet: they get a service with the phone / connectivity work
    property bool bt: true
    property bool wifi: false

    readonly property var itemCounts: [2, 3, 9, 3, 2, 1]
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
            if (item === 0) Sim.setSetting("clock_24h", !Sim.clock24h);
            else Sim.setSetting("units", Sim.units_metric ? "imperial" : "metric");
        } else if (cat === 1) {
            if (item === 0) Sim.setSetting("brightness", Math.round(Math.min(1, Math.max(0.2, Sim.brightness + d * 0.1)) * 100) / 100);
            else if (item === 1) Sim.setSetting("accent", Theme.accents[(Theme.accentIndex + d + Theme.accents.length) % Theme.accents.length].key);
            else Sim.setSetting("night_dimming", !Sim.nightDimming);
        } else if (cat === 2) {
            const vol = (v) => Math.min(Sim.volumeMax, Math.max(0, v + d));
            if (item === 0) Sim.mediaVolume = vol(Sim.mediaVolume);
            else if (item === 1) Sim.navVolume = vol(Sim.navVolume);
            else if (item === 2) Sim.phoneVolume = vol(Sim.phoneVolume);
            else if (item === 3) Sim.radioVolume = vol(Sim.radioVolume);
            else if (item === 4) Sim.chimeVolume = vol(Sim.chimeVolume);
            else if (item === 5) Sim.setTone("bass", Math.min(6, Math.max(-6, Sim.toneBass + d)));
            else if (item === 6) Sim.setTone("treble", Math.min(6, Math.max(-6, Sim.toneTreble + d)));
            else if (item === 7) Sim.setTone("balance", Math.round(Math.min(1, Math.max(-1, Sim.toneBalance + d * 0.2)) * 10) / 10);
            else Sim.setTone("loudness", !Sim.loudness);
        } else if (cat === 3) {
            if (item === 0) Sim.phoneSetConsent(Sim.phoneConsent !== "yes");
            else if (item === 1) Sim.phoneSync();
            else Sim.phoneDeleteCopy();
        } else if (cat === 4) {
            if (item === 0) bt = !bt; else wifi = !wifi;
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
            SettingRow { label: "24-hour clock"; idx: 0
                Toggle { anchors.verticalCenter: parent.verticalCenter; checked: Sim.clock24h; onToggled: Sim.setSetting("clock_24h", !Sim.clock24h) } }
            SettingRow { label: "Metric units"; idx: 1
                Toggle { anchors.verticalCenter: parent.verticalCenter; checked: Sim.units_metric
                         onToggled: Sim.setSetting("units", Sim.units_metric ? "imperial" : "metric") } }
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
                LineSlider { anchors.verticalCenter: parent.verticalCenter; width: 360; from: 0.2; to: 1; value: Sim.brightness
                             focused: root.inPanel && root.item === 0
                             onMoved: (v) => Sim.setSetting("brightness", Math.round(v * 100) / 100) } }
            SettingRow { label: "Accent colour"; idx: 1
                Row {
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 18
                    Repeater {
                        model: Theme.accents
                        Rectangle {
                            width: 50; height: 50; radius: 25
                            color: modelData.color
                            border.color: index === Theme.accentIndex ? Theme.selectionRing : "transparent"
                            border.width: 3
                            MouseArea { anchors.fill: parent; onClicked: Sim.setSetting("accent", modelData.key) }
                        }
                    }
                }
            }
            SettingRow { label: "Dim at night"; idx: 2
                Toggle { anchors.verticalCenter: parent.verticalCenter; checked: Sim.nightDimming; onToggled: Sim.setSetting("night_dimming", !Sim.nightDimming) } }
            T { x: 18; text: Theme.accents[Theme.accentIndex].name; color: Theme.accentMid; font.pixelSize: Theme.fontSmall }
        }

        // Audio: one volume per source (D9; the master volume is in the volume popup), then tone
        Column {
            visible: root.cat === 2
            spacing: 4
            Repeater {
                model: [{ label: "Media", key: "mediaVolume" }, { label: "Navigation", key: "navVolume" },
                        { label: "Phone", key: "phoneVolume" }, { label: "Radio", key: "radioVolume" },
                        { label: "Chimes", key: "chimeVolume" }]
                SettingRow {
                    label: modelData.label + "  " + Sim[modelData.key]; idx: index; height: 66
                    LineSlider { anchors.verticalCenter: parent.verticalCenter; width: 360; from: 0; to: Sim.volumeMax
                                 value: Sim[modelData.key]
                                 focused: root.inPanel && root.item === index
                                 onMoved: (v) => Sim[modelData.key] = Math.round(v) }
                }
            }
            SettingRow { label: "Bass  " + (Sim.toneBass > 0 ? "+" : "") + Sim.toneBass; idx: 5; height: 66
                LineSlider { anchors.verticalCenter: parent.verticalCenter; width: 360; from: -6; to: 6; value: Sim.toneBass; centered: true
                             focused: root.inPanel && root.item === 5; onMoved: (v) => Sim.setTone("bass", Math.round(v)) } }
            SettingRow { label: "Treble  " + (Sim.toneTreble > 0 ? "+" : "") + Sim.toneTreble; idx: 6; height: 66
                LineSlider { anchors.verticalCenter: parent.verticalCenter; width: 360; from: -6; to: 6; value: Sim.toneTreble; centered: true
                             focused: root.inPanel && root.item === 6; onMoved: (v) => Sim.setTone("treble", Math.round(v)) } }
            SettingRow { label: "Balance"; idx: 7; height: 66
                LineSlider { anchors.verticalCenter: parent.verticalCenter; width: 360; from: -1; to: 1; value: Sim.toneBalance; centered: true
                             focused: root.inPanel && root.item === 7; onMoved: (v) => Sim.setTone("balance", Math.round(v * 10) / 10) } }
            SettingRow { label: "Loudness"; idx: 8; height: 66
                Toggle { anchors.verticalCenter: parent.verticalCenter; checked: Sim.loudness; onToggled: Sim.setTone("loudness", !Sim.loudness) } }
        }

        // Phone: the copy of the connected phone's contacts and call history (hu-phoned)
        Column {
            visible: root.cat === 3
            spacing: 8
            SettingRow { label: "Keep a copy"; idx: 0
                Toggle { anchors.verticalCenter: parent.verticalCenter; checked: Sim.phoneConsent === "yes"
                         onToggled: Sim.phoneSetConsent(Sim.phoneConsent !== "yes") } }
            SettingRow { label: "Contacts and calls"; idx: 1
                LineButton { anchors.verticalCenter: parent.verticalCenter; icon: Icons.reroute; iconSize: 22
                             label: Sim.phoneSyncState === "syncing" ? "Syncing …" : "Sync now"; onClicked: Sim.phoneSync() } }
            SettingRow { label: "Copy on the headunit"; idx: 2
                LineButton { anchors.verticalCenter: parent.verticalCenter; icon: Icons.minus; iconSize: 22
                             label: "Delete"; onClicked: Sim.phoneDeleteCopy() } }
            Item { width: 1; height: 20 }
            Repeater {
                model: [
                    ["Phone", Sim.phoneName],
                    ["Contacts", Sim.phoneContactCount + (Sim.phoneContactCount === 1 ? " contact" : " contacts")],
                    ["Last synced", Sim.phoneSyncedAt > 0 ? Qt.formatDateTime(new Date(Sim.phoneSyncedAt * 1000), Sim.clock24h ? "dd.MM.yyyy HH:mm" : "dd.MM.yyyy h:mm ap") : "never"],
                    ["Status", Sim.phoneSyncState === "syncing" ? "copying from the phone …"
                             : Sim.phoneSyncState === "failed" ? "failed: " + Sim.phoneSyncError
                             : Sim.phoneConsent === "yes" ? "kept" : Sim.phoneConsent === "no" ? "not kept" : "not asked yet"]
                ]
                Row {
                    x: 18; spacing: 14
                    T { width: 200; text: modelData[0]; color: Theme.accentMid; font.pixelSize: Theme.fontSmall + 2 }
                    T { width: 460; text: modelData[1]; font.pixelSize: Theme.fontSmall + 2; elide: Text.ElideRight }
                }
            }
        }

        // Connectivity
        Column {
            visible: root.cat === 4
            spacing: 8
            SettingRow { label: "Bluetooth"; idx: 0
                Toggle { anchors.verticalCenter: parent.verticalCenter; checked: root.bt; onToggled: root.bt = !root.bt } }
            SettingRow { label: "Wi-Fi hotspot"; idx: 1
                Toggle { anchors.verticalCenter: parent.verticalCenter; checked: root.wifi; onToggled: root.wifi = !root.wifi } }
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

        // System: what runs and how the computer is doing (hu-sysd's Info)
        Column {
            id: sysPage
            visible: root.cat === 5
            spacing: 10
            x: 18
            readonly property var i: Sim.systemInfo
            function days(s) {
                if (s === undefined || s < 0) return "--";
                const d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60);
                return (d ? d + " d " : "") + (d || h ? h + " h " : "") + m + " min";
            }
            readonly property var rows: {
                const i = sysPage.i;
                const up = (i.services_up || []).length, missing = i.services_missing || [];
                return [
                    ["System", i.os + "  ·  " + i.kernel],
                    ["Uptime", days(i.uptime_s)],
                    ["CPU", (i.cpu_temp_c >= 0 ? i.cpu_temp_c.toFixed(1) + " °C" : "--")
                            + "  ·  load " + (i.load >= 0 ? i.load.toFixed(2) : "--")],
                    ["Memory", i.mem_total_mb > 0 ? (i.mem_total_mb - i.mem_available_mb) + " of " + i.mem_total_mb + " MB used" : "--"],
                    ["Storage", i.disk_free_mb >= 0 ? (i.disk_free_mb / 1024).toFixed(1) + " GB free" : "--"],
                    ["Services", up + " of " + (up + missing.length) + " running"
                                 + (missing.length ? "  ·  missing " + missing.map(n => n.replace("de.r80.", "")).join(", ") : "")],
                    ["Phone", Sim.navPhone.connected ? Sim.navPhone.device + " (companion app)" : "not connected"],
                    ["Bluetooth", i.bt_name ? i.bt_name + "  ·  " + (i.bt_powered ? "on" : "off") + "  ·  " + i.bt_address
                                            : "no adapter"]
                ];
            }
            readonly property var cells: {
                const o = [];
                for (const r of rows) { o.push(r[0]); o.push(r[1]); }
                return o;
            }
            Row {
                spacing: 24
                Logo { width: 150; height: 46; anchors.verticalCenter: parent.verticalCenter }
                T { text: "R80 Headunit  ·  " + sysPage.i.version; anchors.verticalCenter: parent.verticalCenter }
            }
            Item { width: 1; height: 6 }
            Grid {
                columns: 2
                columnSpacing: 30
                rowSpacing: 9
                Repeater {
                    model: sysPage.cells
                    T {
                        text: modelData
                        width: index % 2 === 0 ? 150 : 560
                        color: index % 2 === 0 ? Theme.accentMid : Theme.accent
                        font.pixelSize: Theme.fontSmall + 2
                    }
                }
            }
            Item { width: 1; height: 4 }
            T { text: "Fonts B612 (OFL/EPL), OSP-DIN (OFL)  ·  icons and line art drawn for R80"
                width: 700; wrapMode: Text.WordWrap; color: Theme.accentMid; font.pixelSize: Theme.fontSmall }
            SettingRow { label: "Simulate incoming call"; idx: 0; x: -18
                LineButton { anchors.verticalCenter: parent.verticalCenter; icon: Icons.phone; label: "Ring"; iconSize: 22; onClicked: Sim.simulateIncomingCall() } }
        }
    }
}
