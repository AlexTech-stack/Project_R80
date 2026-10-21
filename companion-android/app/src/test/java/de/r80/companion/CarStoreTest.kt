package de.r80.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** What the app keeps about the car survives being written and read back. */
class CarStoreTest {
    @Test fun roundTrip() {
        val s = CarStore.Saved(
            CarStatus(1792593600, true, 8.0, 60.0, 187432.4, 12.1, -3.5, -150.0, 20.0, CarStatus.Trip(12.3, 25.0, 30.0),
                listOf(CarStatus.Warning("information", "Fuel low (8 %)")), "amber"),
            1792593601, CarStore.Parked(48.13715, 11.57612, 12.0, 1792593610))
        assertEquals(s, CarStore.decode(CarStore.encode(s)))
    }

    @Test fun nothingParkedYet() {
        val s = CarStore.Saved(CarStatus(5, false), 6, null)
        assertEquals(s, CarStore.decode(CarStore.encode(s)))
    }

    @Test fun brokenFileIsNothing() {
        assertNull(CarStore.decode("""{"received":5}"""))
    }
}
