pragma Singleton
import QtQuick

// Central look & feel. Everything visual reads from here, so the accent
// colour, brightness and fonts can be changed live from the Settings screen.
QtObject {
    id: theme

    readonly property var accents: [
        { name: "Signal red",   color: "#e3211c" },
        { name: "Amber",        color: "#ff9d1c" },
        { name: "Arctic white", color: "#dde5ee" },
        { name: "Ice blue",     color: "#38b4ff" }
    ]
    property int accentIndex: 0
    readonly property color accent: accents[accentIndex].color
    readonly property color accentMid: Qt.rgba(accent.r, accent.g, accent.b, 0.62)
    readonly property color accentDim: Qt.rgba(accent.r, accent.g, accent.b, 0.35)
    readonly property color accentFaint: Qt.rgba(accent.r, accent.g, accent.b, 0.14)
    readonly property color bg: "#000000"
    readonly property color textOnAccent: "#0a0000"

    // 0.2 .. 1.0, applied as a dimming overlay over the whole display
    property real brightness: 0.9

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
