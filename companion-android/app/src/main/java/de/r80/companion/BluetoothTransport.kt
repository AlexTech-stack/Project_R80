package de.r80.companion

import android.annotation.SuppressLint
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothSocket
import java.io.InputStream
import java.io.OutputStream
import java.util.UUID

/**
 * The real link: Bluetooth RFCOMM to the HU's companion service (hu-navd registers it with
 * BlueZ under Protocol.SERVICE_UUID). The HU must be paired with the phone already; the
 * HU only accepts paired phones. Needs the BLUETOOTH_CONNECT permission.
 */
class BluetoothTransport(private val adapter: BluetoothAdapter, private val address: String) : Transport {
    @Volatile private var socket: BluetoothSocket? = null
    override val description = "Bluetooth $address"

    @SuppressLint("MissingPermission")    // checked before the link starts (MainActivity)
    override fun open(): Pair<InputStream, OutputStream> {
        if (!adapter.isEnabled) throw IllegalStateException("Bluetooth is off")
        val s = adapter.getRemoteDevice(address).createRfcommSocketToServiceRecord(UUID.fromString(Protocol.SERVICE_UUID))
        socket = s
        s.connect()
        return s.inputStream to s.outputStream
    }

    override fun close() {
        try { socket?.close() } catch (_: Exception) {}
    }
}
