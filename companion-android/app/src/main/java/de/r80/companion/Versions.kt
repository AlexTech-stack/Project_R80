package de.r80.companion

/**
 * Software versions of the HU, ordered as hu/services/update.py orders them (semantic
 * versioning: 0.2.0-dev.3+abc < 0.2.0 < 0.10.0; build metadata after '+' does not count).
 */
object Versions {
    private val RE = Regex("""^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+([0-9A-Za-z.-]+))?$""")

    fun valid(v: String) = RE.matches(v)

    /** < 0, 0, > 0 like compareTo; null if one of them is not a version. */
    fun compare(a: String, b: String): Int? {
        val ma = RE.matchEntire(a) ?: return null
        val mb = RE.matchEntire(b) ?: return null
        for (i in 1..3) {
            val c = ma.groupValues[i].toBigInteger().compareTo(mb.groupValues[i].toBigInteger())
            if (c != 0) return c
        }
        val pa = ma.groupValues[4].ifEmpty { null }
        val pb = mb.groupValues[4].ifEmpty { null }
        if (pa == null || pb == null) return (if (pa == null) 1 else 0) - (if (pb == null) 1 else 0)
        val xa = pa.split('.')
        val xb = pb.split('.')
        for (i in 0 until minOf(xa.size, xb.size)) {
            val na = xa[i].toBigIntegerOrNull()
            val nb = xb[i].toBigIntegerOrNull()
            val c = when {
                na != null && nb != null -> na.compareTo(nb)
                na != null -> -1                       // numbers sort before words
                nb != null -> 1
                else -> xa[i].compareTo(xb[i])
            }
            if (c != 0) return c
        }
        return xa.size.compareTo(xb.size)
    }

    /** a is newer than b. A b that is not a version (a development build of the HU): any valid a is. */
    fun newer(a: String, b: String): Boolean {
        if (!valid(a)) return false
        return compare(a, b)?.let { it > 0 } ?: true
    }
}
