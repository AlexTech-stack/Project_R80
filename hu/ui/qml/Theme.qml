pragma Singleton
import QtQuick

// Central look & feel. Everything visual reads from here. Accent colour and brightness
// follow the user's settings (Sim; hu-sysd when live, D12).
QtObject {
    id: theme

    // key = the accent setting's value (hu/system.ini)
    readonly property var accents: [
        { key: "signal_red",   name: "Signal red",   color: "#e3211c" },
        { key: "amber",        name: "Amber",        color: "#ff9d1c" },
        { key: "arctic_white", name: "Arctic white", color: "#dde5ee" },
        { key: "ice_blue",     name: "Ice blue",     color: "#38b4ff" }
    ]
    readonly property int accentIndex: Math.max(0, accents.findIndex(a => a.key === Sim.accent))
    readonly property color accent: accents[accentIndex].color
    readonly property color accentMid: Qt.rgba(accent.r, accent.g, accent.b, 0.62)
    readonly property color accentDim: Qt.rgba(accent.r, accent.g, accent.b, 0.35)
    readonly property color accentFaint: Qt.rgba(accent.r, accent.g, accent.b, 0.14)
    readonly property color bg: "#000000"
    readonly property color textOnAccent: "#0a0000"
    readonly property color shade: "#000000"          // dimming and modal backdrops, used with opacity
    readonly property color selectionRing: "#ffffff"  // ring around the selected accent swatch

    // 0 .. 1, applied as a dimming overlay over the whole display
    readonly property real brightness: Sim.displayBrightness

    // Design resolution of the display (5:3 like the vision sheet).
    readonly property int screenWidth: 1280
    readonly property int screenHeight: 768
    readonly property int headerHeight: 72
    readonly property int margin: 36

    readonly property int fontSmall: 19
    readonly property int fontNormal: 24
    readonly property int fontLarge: 30

    property FontLoader uiFontRegular: FontLoader { source: "../fonts/B612-Regular.otf" }
    property FontLoader uiFontBold: FontLoader { source: "../fonts/B612-Bold.otf" }
    property FontLoader monoFont: FontLoader { source: "../fonts/B612Mono-Regular.otf" }
    property FontLoader dinFont: FontLoader { source: "../fonts/OSP-DIN.ttf" }

    readonly property string fontFamily: uiFontRegular.name
    readonly property string numberFamily: dinFont.name
    readonly property string monoFamily: monoFont.name
}
