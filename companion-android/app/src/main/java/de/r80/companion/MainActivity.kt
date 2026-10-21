package de.r80.companion

import android.Manifest
import android.app.Activity
import android.app.NotificationManager
import android.bluetooth.BluetoothManager
import android.content.ComponentName
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.view.View
import android.widget.AdapterView
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.EditText
import android.widget.RadioGroup
import android.widget.Spinner
import android.widget.Switch
import android.widget.TextView
import android.widget.Toast

/**
 * The app's only screen: notification access, which HU (the paired one over Bluetooth, or a
 * PC running navd with a TCP port over Wi-Fi for development), connect / disconnect, what is
 * sent, and capture mode.
 */
class MainActivity : Activity() {
    private lateinit var access: TextView
    private lateinit var linkStatus: TextView
    private lateinit var guidance: TextView
    private lateinit var captureInfo: TextView
    private lateinit var connect: Button
    private lateinit var devices: Spinner
    private lateinit var address: EditText
    private var paired: List<Pair<String, String>> = emptyList()    // (address, label)
    private val refresh: () -> Unit = { show() }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        access = findViewById(R.id.access)
        linkStatus = findViewById(R.id.link_status)
        guidance = findViewById(R.id.guidance)
        captureInfo = findViewById(R.id.capture_info)
        connect = findViewById(R.id.connect)

        findViewById<Button>(R.id.grant).setOnClickListener {
            startActivity(Intent(android.provider.Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
        }
        address = findViewById(R.id.address)
        address.setText(Settings.huAddress(this))
        devices = findViewById(R.id.hu_device)
        devices.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(p: AdapterView<*>?, v: View?, pos: Int, id: Long) {
                paired.getOrNull(pos)?.let { Settings.setHuDevice(this@MainActivity, it.first) }
            }
            override fun onNothingSelected(p: AdapterView<*>?) {}
        }
        val transport = findViewById<RadioGroup>(R.id.transport)
        transport.check(if (Settings.transport(this) == "wifi") R.id.transport_wifi else R.id.transport_bluetooth)
        transport.setOnCheckedChangeListener { _, id ->
            Settings.setTransport(this, if (id == R.id.transport_wifi) "wifi" else "bluetooth")
            show()
        }
        connect.setOnClickListener {
            if (AppState.link.state == Link.State.STOPPED) {
                if (Settings.transport(this) == "wifi") {
                    if (Settings.parseAddress(address.text.toString()) == null) {
                        Toast.makeText(this, R.string.bad_address, Toast.LENGTH_LONG).show()
                        return@setOnClickListener
                    }
                    Settings.setHuAddress(this, address.text.toString())
                }
                LinkService.start(this)
            } else {
                LinkService.stop(this)
            }
        }
        val surroundings = findViewById<Switch>(R.id.surroundings)
        surroundings.isChecked = Settings.shareSurroundings(this)
        surroundings.setOnCheckedChangeListener { _, on ->
            Settings.setShareSurroundings(this, on)
            if (on && !locationAllowed())
                requestPermissions(arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION), 2)
            if (AppState.link.state != Link.State.STOPPED) Toast.makeText(this, R.string.surroundings_restart, Toast.LENGTH_LONG).show()
            show()
        }
        val capture = findViewById<Switch>(R.id.capture)
        capture.isChecked = Settings.capture(this)
        capture.setOnCheckedChangeListener { _, on -> Settings.setCapture(this, on); show() }
        findViewById<Button>(R.id.export).setOnClickListener {
            try {
                Toast.makeText(this, getString(R.string.exported, Capture.export(this)), Toast.LENGTH_LONG).show()
            } catch (e: Exception) {
                Toast.makeText(this, e.message, Toast.LENGTH_LONG).show()
            }
        }
        findViewById<Button>(R.id.clear).setOnClickListener { Capture.clear(this); show() }

        val wanted = listOf(Manifest.permission.POST_NOTIFICATIONS, Manifest.permission.BLUETOOTH_CONNECT) +
            (if (Settings.shareSurroundings(this)) listOf(Manifest.permission.ACCESS_FINE_LOCATION,
                Manifest.permission.ACCESS_COARSE_LOCATION) else emptyList())
        val missing = wanted.filter { checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED }
        if (missing.isNotEmpty()) requestPermissions(missing.toTypedArray(), 1)
    }

    private fun locationAllowed() =
        checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED ||
            checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        show()
    }

    /** The phone's paired devices, for choosing the HU. */
    @android.annotation.SuppressLint("MissingPermission")    // checked right here
    private fun listPaired() {
        val allowed = checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) == PackageManager.PERMISSION_GRANTED
        paired = if (!allowed) emptyList() else
            getSystemService(BluetoothManager::class.java)?.adapter?.bondedDevices.orEmpty()
                .map { it.address to "${it.name ?: "?"}  (${it.address})" }.sortedBy { it.second }
        val labels = when {
            !allowed -> listOf(getString(R.string.bt_permission))
            paired.isEmpty() -> listOf(getString(R.string.no_paired))
            else -> paired.map { it.second }
        }
        devices.adapter = ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item, labels)
        paired.indexOfFirst { it.first == Settings.huDevice(this) }.takeIf { it >= 0 }?.let { devices.setSelection(it) }
    }

    override fun onResume() {
        super.onResume()
        listPaired()                // the user may have paired the HU meanwhile
        AppState.listen(refresh)
        show()
    }

    override fun onPause() {
        AppState.unlisten(refresh)
        super.onPause()
    }

    private fun show() {
        val granted = getSystemService(NotificationManager::class.java)
            .isNotificationListenerAccessGranted(ComponentName(this, MapsListenerService::class.java))
        access.setText(if (granted) R.string.access_granted else R.string.access_missing)
        val wifi = Settings.transport(this) == "wifi"
        address.visibility = if (wifi) View.VISIBLE else View.GONE
        devices.visibility = if (wifi) View.GONE else View.VISIBLE
        findViewById<View>(R.id.bt_hint).visibility = devices.visibility
        if (!wifi && devices.adapter == null) listPaired()
        val s = AppState.link
        linkStatus.text = getString(R.string.link_status, s.state.name.lowercase(), s.detail)
        connect.setText(if (s.state == Link.State.STOPPED) R.string.connect else R.string.disconnect)
        val g = AppState.guidance
        guidance.text = if (g == null) getString(R.string.no_guidance) else buildString {
            append("${g.maneuver} ${g.modifier ?: ""} ${g.exit ?: ""}".trim())
            g.distanceM?.let { append("  ·  ${it.toInt()} m") }
            g.street?.let { append("  ·  $it") }
            g.text?.let { append("\n$it") }
            if (g.remainingS != null || g.remainingM != null)
                append("\n${g.remainingS?.let { "${(it / 60).toInt()} min" } ?: "--"} · ${g.remainingM?.let { "%.1f km".format(it / 1000) } ?: "--"}")
            append("\n\n").append(AppState.lastRaw)
        }
        captureInfo.text = getString(R.string.capture_info, Capture.count(this))
        val w = AppState.weather
        val p = AppState.position
        findViewById<TextView>(R.id.surroundings_info).text = getString(R.string.surroundings_info, when {
            !Settings.shareSurroundings(this) -> getString(R.string.surroundings_off)
            !locationAllowed() -> getString(R.string.surroundings_permission)
            w == null && p == null -> getString(R.string.surroundings_none)
            else -> getString(R.string.surroundings_sent,
                w?.let { "%.0f °C, code %d".format(it.tempC, it.code) } ?: "--",
                p?.altM?.let { "%.0f m".format(it) } ?: "--")
        })
    }
}
