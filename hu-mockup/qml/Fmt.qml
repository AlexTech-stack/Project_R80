pragma Singleton
import QtQuick

// Number formatting shared by several screens.
QtObject {
    // Distance in metres -> { value, unit } the way a navigation app shows it; null if unknown (< 0).
    function distance(m) {
        if (m === undefined || m < 0) return null;
        if (m >= 10000) return { value: Math.round(m / 1000).toString(), unit: "km" };
        if (m >= 1000) return { value: (m / 1000).toFixed(1), unit: "km" };
        return { value: (m >= 300 ? Math.round(m / 50) * 50 : Math.round(m / 10) * 10).toString(), unit: "m" };
    }
    // A navigation app's street / signpost text -> { main, sub }: the street first, the rest
    // ("Richtung ...", the further destinations of a signpost "A / B / C") as a second line.
    function signpost(s) {
        if (!s) return { main: "", sub: "" };
        const r = s.indexOf(" Richtung ");
        if (r > 0) return { main: s.slice(0, r).trim(), sub: s.slice(r + 1).trim() };
        const parts = s.split(/\s+\/\s+/);
        if (parts.length > 1) return { main: parts[0].trim(), sub: parts.slice(1).join(" / ") };
        return { main: s, sub: "" };
    }
    function distanceText(m) { const d = distance(m); return d ? d.value + " " + d.unit : "--" }
    // Duration in seconds -> "12 min" / "1 h 05 min"; "--" if unknown (< 0).
    function duration(s) {
        if (s === undefined || s < 0) return "--";
        const min = Math.max(1, Math.round(s / 60));
        return min < 60 ? min + " min" : Math.floor(min / 60) + " h " + String(min % 60).padStart(2, "0") + " min";
    }
}
