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
    function distanceText(m) { const d = distance(m); return d ? d.value + " " + d.unit : "--" }
    // Duration in seconds -> "12 min" / "1 h 05 min"; "--" if unknown (< 0).
    function duration(s) {
        if (s === undefined || s < 0) return "--";
        const min = Math.max(1, Math.round(s / 60));
        return min < 60 ? min + " min" : Math.floor(min / 60) + " h " + String(min % 60).padStart(2, "0") + " min";
    }
}
