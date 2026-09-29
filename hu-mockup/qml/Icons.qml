pragma Singleton
import QtQuick

// Self-drawn line icons as SVG path data in a 24x24 box.
// Rendered by Icon.qml with the current accent colour.
QtObject {
    function circle(cx, cy, r) {
        return "M" + (cx + r) + " " + cy + " A" + r + " " + r + " 0 1 1 " + (cx - r) + " " + cy
             + " A" + r + " " + r + " 0 1 1 " + (cx + r) + " " + cy + " ";
    }
    function _gear() {
        let s = "";
        const n = 8, rin = 7.2, rout = 9.8, cx = 12, cy = 12;
        for (let i = 0; i < n; i++) {
            const b = i * 2 * Math.PI / n;
            const pts = [[rin, b - 0.36], [rout, b - 0.2], [rout, b + 0.2], [rin, b + 0.36]];
            for (let j = 0; j < pts.length; j++) {
                const x = (cx + pts[j][0] * Math.cos(pts[j][1])).toFixed(2);
                const y = (cy + pts[j][0] * Math.sin(pts[j][1])).toFixed(2);
                s += (i === 0 && j === 0 ? "M" : "L") + x + " " + y + " ";
            }
        }
        return s + "Z " + circle(12, 12, 3.2);
    }
    function _sun(rc, r0, r1, cx, cy) {
        cx = cx === undefined ? 12 : cx; cy = cy === undefined ? 12 : cy;
        let s = circle(cx, cy, rc);
        for (let i = 0; i < 8; i++) {
            const a = i * Math.PI / 4;
            s += "M" + (cx + r0 * Math.cos(a)).toFixed(2) + " " + (cy + r0 * Math.sin(a)).toFixed(2)
               + " L" + (cx + r1 * Math.cos(a)).toFixed(2) + " " + (cy + r1 * Math.sin(a)).toFixed(2) + " ";
        }
        return s;
    }

    readonly property string nav: "M12 2.5 L19.5 21 L12 16.5 L4.5 21 Z"
    readonly property string music: "M9 18 V5 L20 3 V16 " + circle(6.5, 18, 2.5) + circle(17.5, 16, 2.5)
    readonly property string phone: "M5.5 3 H9 L10.8 7.8 L8.3 9.4 A12 12 0 0 0 14.6 15.7 L16.2 13.2 L21 15 V18.5 A2.5 2.5 0 0 1 18.5 21 A16.5 16.5 0 0 1 3 5.5 A2.5 2.5 0 0 1 5.5 3 Z"
    readonly property string car: "M3 18 V12.5 L5.2 7 Q5.6 6 6.8 6 H17.2 Q18.4 6 18.8 7 L21 12.5 V18 Z M3 12.5 H21 M5 18 V20.5 H7.5 V18 M16.5 18 V20.5 H19 V18 M5.5 15 H8 M16 15 H18.5 M10 15.5 H14"
    readonly property string gauge: "M4.2 18 A9 9 0 1 1 19.8 18 M12 13 L16.5 7.5 " + circle(12, 13, 1.2) + "M5.5 12 H7 M12 5.5 V7 M18.5 12 H17"
    readonly property string radio: "M12 7 L7 21.5 M12 7 L17 21.5 M8.8 16.5 H15.2 M9.8 13 H14.2 M7.6 20 H16.4 " + circle(12, 5.5, 1.3)
                                    + "M8 2.5 A5 5 0 0 0 8 8.5 M16 2.5 A5 5 0 0 1 16 8.5"
    readonly property string clock: circle(12, 12, 9) + "M12 6.5 V12 L15.5 14.5"
    readonly property string gear: _gear()
    readonly property string sun: _sun(4, 6.5, 9.5)
    readonly property string brightness: _sun(4, 6.5, 9.5) + "M12 8 A4 4 0 0 0 12 16 Z"
    readonly property string home: "M3 11.5 L12 3.5 L21 11.5 M5.5 9.5 V20.5 H18.5 V9.5 M10 20.5 V14.5 H14 V20.5"
    readonly property string back: "M15 4.5 L7.5 12 L15 19.5"
    readonly property string chevronRight: "M9 4.5 L16.5 12 L9 19.5"
    readonly property string prev: "M6 5 V19 M19 5 L9 12 L19 19 Z"
    readonly property string next: "M18 5 V19 M5 5 L15 12 L5 19 Z"
    readonly property string play: "M7 4.5 L19.5 12 L7 19.5 Z"
    readonly property string pause: "M8 5 V19 M16 5 V19"
    readonly property string shuffle: "M3 7 H7 L15 17 H20 M3 17 H7 L9.5 14 M13 10 L15 7 H20 M17.5 4.5 L20 7 L17.5 9.5 M17.5 14.5 L20 17 L17.5 19.5"
    readonly property string repeat: "M4 11 V9 A3 3 0 0 1 7 6 H19 M16 3 L19 6 L16 9 M20 13 V15 A3 3 0 0 1 17 18 H5 M8 21 L5 18 L8 15"
    readonly property string signal: "M3 20.5 H6 V16.5 H3 Z M8 20.5 H11 V12.5 H8 Z M13 20.5 H16 V8.5 H13 Z M18 20.5 H21 V4 H18 Z"
    readonly property string bluetooth: "M6.5 7 L17 16.5 L12 21 V3 L17 7.5 L6.5 17"
    readonly property string display: "M3 4.5 H21 V16 H3 Z M8.5 20.5 H15.5 M12 16 V20.5"
    readonly property string speaker: "M3.5 9 H7.5 L12.5 5 V19 L7.5 15 H3.5 Z M15.5 9 A4 4 0 0 1 15.5 15 M18 6.5 A7.5 7.5 0 0 1 18 17.5"
    readonly property string mute: "M3.5 9 H7.5 L12.5 5 V19 L7.5 15 H3.5 Z M15.5 9 L21 15 M21 9 L15.5 15"
    readonly property string wifi: "M2 9.5 A14 14 0 0 1 22 9.5 M5 13 A9.5 9.5 0 0 1 19 13 M8.2 16.4 A5 5 0 0 1 15.8 16.4 M12 20 L12 20.1"
    readonly property string chip: "M7 7 H17 V17 H7 Z M10 10 H14 V14 H10 Z M9.5 3 V7 M14.5 3 V7 M9.5 17 V21 M14.5 17 V21 M3 9.5 H7 M3 14.5 H7 M17 9.5 H21 M17 14.5 H21"
    readonly property string mountain: "M2 20 L9 8 L13 14 L16 10 L22 20 Z"
    readonly property string cloud: "M7 18 H17.5 A3.5 3.5 0 0 0 17.5 11 A5.5 5.5 0 0 0 7 10 A4 4 0 0 0 7 18 Z"
    readonly property string partCloud: _sun(2.8, 4.6, 6.4, 8.5, 8.5) + "M9 20 H18 A3 3 0 0 0 18 14 A4.5 4.5 0 0 0 9.5 13.5 A3.3 3.3 0 0 0 9 20 Z"
    readonly property string rain: "M7 15 H17.5 A3.5 3.5 0 0 0 17.5 8 A5.5 5.5 0 0 0 7 7 A4 4 0 0 0 7 15 Z M8 18 L7 21 M12 18 L11 21 M16 18 L15 21"
    readonly property string oil: "M2.5 10 H9.5 L11.5 8 H14 L21.5 11.5 L14.5 16.5 H4.5 A2 2 0 0 1 2.5 14.5 Z M6 8 V10 M4 8 H8 M21.5 15 V16"
    readonly property string coolant: "M12 2.5 A2 2 0 0 1 14 4.5 V13 A4 4 0 1 1 10 13 V4.5 A2 2 0 0 1 12 2.5 Z M12 8 V16 M16.5 5 H19 M16.5 8.5 H19 M16.5 12 H19"
    readonly property string battery: "M2.5 7.5 H21.5 V19.5 H2.5 Z M5.5 7.5 V5 H9 V7.5 M15 7.5 V5 H18.5 V7.5 M5.5 13.5 H9.5 M14.5 13.5 H18.5 M16.5 11.5 V15.5"
    readonly property string fuel: "M4 21 V4.5 A1.5 1.5 0 0 1 5.5 3 H12.5 A1.5 1.5 0 0 1 14 4.5 V21 Z M2.5 21 H15.5 M6.5 6 H11.5 V10 H6.5 Z M14 11 H15.5 A1 1 0 0 1 16.5 12 V17 A1.7 1.7 0 0 0 20 17 V8.5 L17 5.5"
    readonly property string tyre: circle(12, 12, 9) + circle(12, 12, 4.5) + "M12 3 V7.5 M12 16.5 V21 M3 12 H7.5 M16.5 12 H21"
    readonly property string wrench: "M14.5 3.5 A5 5 0 0 0 11 10 L3.5 17.5 A2 2 0 0 0 6.5 20.5 L14 13 A5 5 0 0 0 20.5 9.5 L17 11 L13 7 Z"
    readonly property string route: circle(6, 18, 2.2) + circle(18, 6, 2.2) + "M8 18 H15 A3 3 0 0 0 15 12 H9 A3 3 0 0 1 9 6 H16"
    readonly property string mic: "M9 4.5 A3 3 0 0 1 15 4.5 V11.5 A3 3 0 0 1 9 11.5 Z M5.5 11 A6.5 6.5 0 0 0 18.5 11 M12 17.5 V21 M8.5 21 H15.5"
    readonly property string micOff: mic + "M4 3 L20 21"
    readonly property string keypad: circle(6, 5, 1.2) + circle(12, 5, 1.2) + circle(18, 5, 1.2) + circle(6, 10.5, 1.2) + circle(12, 10.5, 1.2) + circle(18, 10.5, 1.2) + circle(6, 16, 1.2) + circle(12, 16, 1.2) + circle(18, 16, 1.2) + circle(12, 21, 1.2)
    readonly property string person: circle(12, 8, 4) + "M4 21 A8 7 0 0 1 20 21"
    readonly property string star: "M12 3 L14.7 9 L21 9.6 L16.2 13.8 L17.6 20.2 L12 16.9 L6.4 20.2 L7.8 13.8 L3 9.6 L9.3 9 Z"
    readonly property string search: circle(10.5, 10.5, 6.5) + "M15.5 15.5 L21 21"
    readonly property string plus: "M12 5 V19 M5 12 H19"
    readonly property string minus: "M5 11.99 L19 12.01"
    readonly property string compassN: circle(12, 12, 9) + "M9 16 V8 L15 16 V8"
    readonly property string headingUp: circle(12, 12, 9) + "M12 5.5 L16 16.5 L12 14 L8 16.5 Z"
    readonly property string hangup: "M2.5 14 Q12 5.5 21.5 14 L19.5 17.5 L15.5 15.8 V13 Q12 11.8 8.5 13 V15.8 L4.5 17.5 Z"
    readonly property string callIn: "M20 4 L13 11 M13 5.5 V11 H18.5"
    readonly property string callOut: "M13 11 L20 4 M14.5 4 H20 V9.5"
    readonly property string callMissed: "M4 7 L9 12 L14 7 M20 4 L14 10"
    readonly property string flag: "M6 21.5 V3 M6 4 H18.5 L15.5 8.5 L18.5 13 H6"
    readonly property string turnRight: "M7 21.5 V12 A4 4 0 0 1 11 8 H18.5 M14.5 4 L18.5 8 L14.5 12"
    readonly property string turnLeft: "M17 21.5 V12 A4 4 0 0 0 13 8 H5.5 M9.5 4 L5.5 8 L9.5 12"
    readonly property string straight: "M12 21.5 V3.5 M7 8.5 L12 3.5 L17 8.5"
    readonly property string globe: circle(12, 12, 9) + "M3 12 H21 M12 3 A13 13 0 0 1 12 21 A13 13 0 0 1 12 3"
    readonly property string power: "M12 3 V11 M7 5.8 A8 8 0 1 0 17 5.8"
    readonly property string usb: "M12 21 V3.5 M9.5 6 L12 3.5 L14.5 6 M12 16 L7 12.5 V9.5 M12 13.5 L17 10.5 V8 " + circle(12, 19.5, 1.5) + "M6 8 H8 V10 H6 Z" + circle(17, 7, 1)
    readonly property string list: "M8 6 H21 M8 12 H21 M8 18 H21 M3.5 6 H4.5 M3.5 12 H4.5 M3.5 18 H4.5"
}
