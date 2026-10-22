package de.r80.companion

import android.Manifest
import android.app.Activity
import android.app.NotificationManager
import android.bluetooth.BluetoothManager
import android.content.ComponentName
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.net.Uri
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ScrollView
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
 * The app's screen in the HU's look (Hu): a header with the R80 mark and the link, and tabs.
 * Car: how the car was when the HU last told (CarStore): live while connected, else where
 * and how it was parked. Settings: notification access, which HU (the paired one over
 * Bluetooth, or a PC running navd with a TCP port over Wi-Fi for development), connect /
 * disconnect, weather and altitude, what is sent, capture mode.
 */
class MainActivity : Activity() {
    private lateinit var root: LinearLayout
    private lateinit var header: LinearLayout
    private lateinit var tabBar: FrameLayout
    private lateinit var page: FrameLayout
    private lateinit var settingsPage: View
    private val carPage by lazy { ScrollView(this) }
    private val remote by lazy { RemotePage(this) }
    private var tab = 0                      // 0 Car, 1 Remote, 2 Settings
    private val ticker = android.os.Handler(android.os.Looper.getMainLooper())
    private val tick = object : Runnable {
        override fun run() {
            if (tab == 1) remote.tick()
            ticker.postDelayed(this, 1000)
        }
    }

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
        Hu.init(this)
        window.statusBarColor = Hu.BG
        window.navigationBarColor = Hu.BG
        root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Hu.BG)
            fitsSystemWindows = true
        }
        header = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(Hu.dp(context, 20f), Hu.dp(context, 14f), Hu.dp(context, 20f), Hu.dp(context, 6f))
        }
        tabBar = FrameLayout(this).apply { setPadding(Hu.dp(context, 20f), 0, Hu.dp(context, 20f), 0) }
        page = FrameLayout(this)
        root.addView(header)
        root.addView(tabBar)
        root.addView(page, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
        setContentView(root)
        settingsPage = layoutInflater.inflate(R.layout.activity_main, page, false).apply { fitsSystemWindows = false }
        tab = if (CarStore.get(this) != null) 0 else 2
        // the link was on (e.g. before an app update stopped it): on again
        if (Settings.linkWanted(this) && AppState.link.state == Link.State.STOPPED) LinkService.start(this)
        access = settingsPage.findViewById(R.id.access)
        linkStatus = settingsPage.findViewById(R.id.link_status)
        guidance = settingsPage.findViewById(R.id.guidance)
        captureInfo = settingsPage.findViewById(R.id.capture_info)
        connect = settingsPage.findViewById(R.id.connect)

        settingsPage.findViewById<Button>(R.id.grant).setOnClickListener {
            startActivity(Intent(android.provider.Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
        }
        address = settingsPage.findViewById(R.id.address)
        address.setText(Settings.huAddress(this))
        devices = settingsPage.findViewById(R.id.hu_device)
        devices.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(p: AdapterView<*>?, v: View?, pos: Int, id: Long) {
                val chosen = paired.getOrNull(pos)?.first ?: return
                if (chosen == Settings.huDevice(this@MainActivity)) return     // also: the list was filled
                Settings.setHuDevice(this@MainActivity, chosen)
                // a running link (it also retries by itself) keeps its HU until told
                if (AppState.link.state != Link.State.STOPPED) LinkService.restart(this@MainActivity)
            }
            override fun onNothingSelected(p: AdapterView<*>?) {}
        }
        val transport = settingsPage.findViewById<RadioGroup>(R.id.transport)
        transport.check(if (Settings.transport(this) == "wifi") R.id.transport_wifi else R.id.transport_bluetooth)
        transport.setOnCheckedChangeListener { _, id ->
            Settings.setTransport(this, if (id == R.id.transport_wifi) "wifi" else "bluetooth")
            if (AppState.link.state != Link.State.STOPPED) LinkService.restart(this)
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
                Settings.setLinkWanted(this, true)
                LinkService.start(this)
            } else {
                Settings.setLinkWanted(this, false)
                LinkService.stop(this)
            }
        }
        val surroundings = settingsPage.findViewById<Switch>(R.id.surroundings)
        surroundings.isChecked = Settings.shareSurroundings(this)
        surroundings.setOnCheckedChangeListener { _, on ->
            Settings.setShareSurroundings(this, on)
            if (on && !locationAllowed())
                requestPermissions(arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION), 2)
            if (AppState.link.state != Link.State.STOPPED) Toast.makeText(this, R.string.surroundings_restart, Toast.LENGTH_LONG).show()
            show()
        }
        val capture = settingsPage.findViewById<Switch>(R.id.capture)
        capture.isChecked = Settings.capture(this)
        capture.setOnCheckedChangeListener { _, on -> Settings.setCapture(this, on); show() }
        settingsPage.findViewById<Button>(R.id.export).setOnClickListener {
            try {
                Toast.makeText(this, getString(R.string.exported, Capture.export(this)), Toast.LENGTH_LONG).show()
            } catch (e: Exception) {
                Toast.makeText(this, e.message, Toast.LENGTH_LONG).show()
            }
        }
        settingsPage.findViewById<Button>(R.id.clear).setOnClickListener { Capture.clear(this); show() }

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
        devices.adapter = object : ArrayAdapter<String>(this, android.R.layout.simple_spinner_dropdown_item, labels) {
            override fun getView(position: Int, convertView: View?, parent: ViewGroup) =
                super.getView(position, convertView, parent).also { (it as TextView).setTextColor(Hu.accent) }
            override fun getDropDownView(position: Int, convertView: View?, parent: ViewGroup) =
                super.getDropDownView(position, convertView, parent).also {
                    (it as TextView).setTextColor(Hu.accent); it.setBackgroundColor(Hu.BG)
                }
        }
        paired.indexOfFirst { it.first == Settings.huDevice(this) }.takeIf { it >= 0 }?.let { devices.setSelection(it) }
    }

    override fun onResume() {
        super.onResume()
        listPaired()                // the user may have paired the HU meanwhile
        AppState.listen(refresh)
        ticker.post(tick)
        show()
    }

    override fun onPause() {
        AppState.unlisten(refresh)
        ticker.removeCallbacks(tick)
        super.onPause()
    }

    // ---- the frame: header and tabs -------------------------------------------------
    private fun frame() {
        header.removeAllViews()
        header.addView(Hu.logo(this))
        header.addView(Hu.text(this, getString(R.string.app_title), 20f).apply {
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply { marginStart = Hu.dp(context, 16f) }
        })
        val on = AppState.link.state == Link.State.CONNECTED
        header.addView(Hu.icon(this, R.drawable.hu_bluetooth, 24f, if (on) Hu.accent else Hu.dim))
        tabBar.removeAllViews()
        tabBar.addView(Hu.tabs(this, listOf(getString(R.string.tab_car), getString(R.string.tab_remote),
            getString(R.string.tab_settings)), tab) { tab = it; show() })
        page.removeAllViews()
        page.addView(when (tab) { 0 -> carPage; 1 -> remote.view; else -> settingsPage })
        Hu.style(settingsPage)
    }

    // ---- Car: how it is / how it was parked ------------------------------------------
    private fun carContent(): View {
        val col = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(Hu.dp(context, 20f), Hu.dp(context, 12f), Hu.dp(context, 20f), Hu.dp(context, 24f))
        }
        val saved = CarStore.get(this)
        if (saved == null) {
            col.addView(Hu.text(this, getString(R.string.car_none), 16f, Hu.mid))
            return col
        }
        val s = saved.status
        val now = System.currentTimeMillis() / 1000
        val live = AppState.link.state == Link.State.CONNECTED && !s.final && now - saved.receivedAt < 180
        col.addView(Hu.text(this, when {
            live -> getString(R.string.car_live)
            s.final -> getString(R.string.car_parked, clock(s.time), ago(now - s.time))
            else -> getString(R.string.car_last, clock(saved.receivedAt), ago(now - saved.receivedAt))
        }, 14f, Hu.mid).apply { setPadding(0, 0, 0, Hu.dp(context, 8f)) })

        fun row(icon: Int, label: Int, value: String?) { col.addView(Hu.dataRow(this, icon, getString(label), value ?: "–")) }
        row(R.drawable.hu_fuel, R.string.car_range, s.rangeKm?.let { "%.0f km".format(it) })
        row(R.drawable.hu_fuel, R.string.car_fuel, s.fuelPct?.let { "%.0f %%".format(it) })
        row(R.drawable.hu_car, R.string.car_odometer, s.odometerKm?.let { "%,d km".format(java.util.Locale.GERMANY, it.toLong()) })
        row(R.drawable.hu_battery, R.string.car_battery, s.batteryV?.let { "%.1f V".format(java.util.Locale.ROOT, it) })
        row(R.drawable.hu_sun, R.string.car_outside, s.outsideC?.let { "%.0f °C".format(it) })
        row(R.drawable.hu_wrench, R.string.car_service, service(s))

        col.addView(section(R.string.car_warnings))
        if (s.warnings.isEmpty()) col.addView(Hu.text(this, getString(R.string.car_no_warnings), 15f, Hu.mid))
        for (w in s.warnings) col.addView(LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(0, Hu.dp(context, 6f), 0, Hu.dp(context, 6f))
            addView(Hu.icon(context, if (w.severity == "warning") R.drawable.hu_warning else R.drawable.hu_info, 24f,
                if (w.severity == "notice") Hu.mid else Hu.accent))
            addView(Hu.text(context, w.text, 15f, if (w.severity == "notice") Hu.mid else Hu.accent).apply {
                setPadding(Hu.dp(context, 14f), 0, 0, 0)
            })
        })

        s.trip?.let { t ->
            col.addView(section(R.string.car_trip))
            col.addView(Hu.text(this, listOfNotNull(
                t.km?.let { "%.1f km".format(java.util.Locale.ROOT, it) },
                t.minutes?.let { "%d:%02d h".format(it.toInt() / 60, it.toInt() % 60) },
                t.avgKmh?.let { "Ø %.0f km/h".format(it) }).joinToString("   ·   "), 20f, numbers = true))
        }

        col.addView(section(R.string.car_parking))
        val p = saved.parked
        if (p == null) {
            col.addView(Hu.text(this, getString(R.string.car_no_parking), 15f, Hu.mid))
        } else {
            col.addView(Hu.text(this, "%.5f, %.5f".format(java.util.Locale.ROOT, p.lat, p.lon), 20f, numbers = true))
            col.addView(Hu.text(this, listOfNotNull(clock(p.time) + ", " + ago(now - p.time),
                p.accuracyM?.let { "± %.0f m".format(it) }).joinToString("   ·   "), 14f, Hu.mid))
            col.addView(Hu.lineButton(this, getString(R.string.car_open_map), R.drawable.hu_nav) {
                val uri = Uri.parse("geo:${p.lat},${p.lon}?q=${p.lat},${p.lon}(R80)")
                try { startActivity(Intent(Intent.ACTION_VIEW, uri)) } catch (_: Exception) {
                    Toast.makeText(this, R.string.car_no_map_app, Toast.LENGTH_LONG).show()
                }
            }.apply {
                layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT)
                    .apply { topMargin = Hu.dp(context, 12f) }
            })
        }
        return col
    }

    private fun section(title: Int) = Hu.text(this, getString(title), 18f, strong = true).apply {
        setPadding(0, Hu.dp(context, 24f), 0, Hu.dp(context, 8f))
    }

    private fun service(s: CarStatus): String? {
        val km = s.serviceKm
        val days = s.serviceDays
        if (km == null && days == null) return null
        if ((km ?: 0.0) < 0 || (days ?: 0.0) < 0)
            return getString(R.string.car_service_overdue)
        return listOfNotNull(km?.let { "%,d km".format(java.util.Locale.GERMANY, it.toLong()) },
                             days?.let { getString(R.string.car_days, it.toInt()) }).joinToString(" / ")
    }

    private fun clock(unix: Long): String =
        android.text.format.DateFormat.getTimeFormat(this).format(java.util.Date(unix * 1000))

    private fun ago(s: Long): String = when {
        s < 90 -> getString(R.string.ago_now)
        s < 3600 -> getString(R.string.ago_min, s / 60)
        s < 48 * 3600 -> getString(R.string.ago_h, s / 3600)
        else -> getString(R.string.ago_days, s / 86400)
    }

    private fun show() {
        CarStore.get(this)?.status?.accent?.let { Hu.setAccent(it) }     // the HU's accent, once it told
        frame()
        if (tab == 0) {
            carPage.removeAllViews()
            carPage.addView(carContent())
            return
        }
        if (tab == 1) {
            remote.show()
            return
        }
        val granted = getSystemService(NotificationManager::class.java)
            .isNotificationListenerAccessGranted(ComponentName(this, MapsListenerService::class.java))
        access.setText(if (granted) R.string.access_granted else R.string.access_missing)
        val wifi = Settings.transport(this) == "wifi"
        address.visibility = if (wifi) View.VISIBLE else View.GONE
        devices.visibility = if (wifi) View.GONE else View.VISIBLE
        settingsPage.findViewById<View>(R.id.bt_hint).visibility = devices.visibility
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
        settingsPage.findViewById<TextView>(R.id.surroundings_info).text = getString(R.string.surroundings_info, when {
            !Settings.shareSurroundings(this) -> getString(R.string.surroundings_off)
            !locationAllowed() -> getString(R.string.surroundings_permission)
            w == null && p == null -> getString(R.string.surroundings_none)
            else -> getString(R.string.surroundings_sent,
                w?.let { "%.0f °C, code %d".format(it.tempC, it.code) } ?: "--",
                p?.altM?.let { "%.0f m".format(it) } ?: "--")
        })
    }
}
