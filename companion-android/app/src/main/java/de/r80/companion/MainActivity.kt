package de.r80.companion

import android.Manifest
import android.app.Activity
import android.app.NotificationManager
import android.content.ComponentName
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.Switch
import android.widget.TextView
import android.widget.Toast

/**
 * The app's only screen: notification access, the HU's address (development: the PC
 * running navd --tcp), connect / disconnect, what is sent, and capture mode.
 */
class MainActivity : Activity() {
    private lateinit var access: TextView
    private lateinit var linkStatus: TextView
    private lateinit var guidance: TextView
    private lateinit var captureInfo: TextView
    private lateinit var connect: Button
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
        val address = findViewById<EditText>(R.id.address)
        address.setText(Settings.huAddress(this))
        connect.setOnClickListener {
            if (AppState.link.state == Link.State.STOPPED) {
                if (Settings.parseAddress(address.text.toString()) == null) {
                    Toast.makeText(this, R.string.bad_address, Toast.LENGTH_LONG).show()
                    return@setOnClickListener
                }
                Settings.setHuAddress(this, address.text.toString())
                LinkService.start(this)
            } else {
                LinkService.stop(this)
            }
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

        if (checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1)
        }
    }

    override fun onResume() {
        super.onResume()
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
    }
}
