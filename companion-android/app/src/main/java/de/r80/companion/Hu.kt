package de.r80.companion

import android.content.Context
import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.StateListDrawable
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.CompoundButton
import android.widget.EditText
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView

/**
 * The HU's look on the phone, so the two clearly belong together: black, line art in the
 * accent colour (the same choices and alpha levels as hu/ui/qml/Theme.qml), the HU's fonts
 * (B612 for text, OSP-DIN for numbers: hu/ui/fonts, the app's assets) and the HU's icons
 * (res/drawable/hu_*, made from Icons.qml by tools/make_icons.py). The accent is the one
 * the HU last told (car_status), red until then.
 */
object Hu {
    /** key -> colour, as in Theme.qml (the HU's accent setting) */
    val ACCENTS = mapOf("signal_red" to 0xFFE3211C.toInt(), "amber" to 0xFFFF9D1C.toInt(),
                        "arctic_white" to 0xFFDDE5EE.toInt(), "ice_blue" to 0xFF38B4FF.toInt())
    const val BG = Color.BLACK

    var accent: Int = ACCENTS.getValue("signal_red")
        private set
    val mid get() = alpha(accent, 0.62f)
    val dim get() = alpha(accent, 0.35f)
    val faint get() = alpha(accent, 0.14f)
    val onAccent = 0xFF0A0000.toInt()

    private var text: Typeface? = null
    private var bold: Typeface? = null
    private var number: Typeface? = null

    fun init(ctx: Context) {
        if (text == null) {
            text = Typeface.createFromAsset(ctx.assets, "B612-Regular.otf")
            bold = Typeface.createFromAsset(ctx.assets, "B612-Bold.otf")
            number = Typeface.createFromAsset(ctx.assets, "OSP-DIN.ttf")
        }
        CarStore.get(ctx)?.status?.accent?.let { setAccent(it) }
    }

    /** true if it changed */
    fun setAccent(key: String): Boolean {
        val c = ACCENTS[key] ?: return false
        if (c == accent) return false
        accent = c
        return true
    }

    fun alpha(c: Int, a: Float) = Color.argb((a * 255).toInt(), Color.red(c), Color.green(c), Color.blue(c))
    fun dp(ctx: Context, v: Float) = TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v, ctx.resources.displayMetrics).toInt()

    // ---- building blocks -----------------------------------------------------------
    fun text(ctx: Context, s: CharSequence = "", sp: Float = 16f, color: Int = accent, numbers: Boolean = false,
             strong: Boolean = false) = TextView(ctx).apply {
        text = s
        setTextColor(color)
        setTextSize(TypedValue.COMPLEX_UNIT_SP, sp)
        typeface = if (numbers) number else if (strong) bold else this@Hu.text
    }

    fun icon(ctx: Context, res: Int, sizeDp: Float = 28f, color: Int = accent) = ImageView(ctx).apply {
        setImageResource(res)
        imageTintList = ColorStateList.valueOf(color)
        layoutParams = LinearLayout.LayoutParams(dp(ctx, sizeDp), dp(ctx, sizeDp))
    }

    /** The outlined button of the HU (LineButton.qml): accent frame, filled while pressed. */
    fun lineButton(ctx: Context, label: String, iconRes: Int? = null, onClick: () -> Unit) = LinearLayout(ctx).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER
        val pad = dp(ctx, 14f)
        setPadding(pad, dp(ctx, 10f), pad, dp(ctx, 10f))
        background = outline(ctx)
        if (iconRes != null) addView(icon(ctx, iconRes, 22f).apply {
            (layoutParams as LinearLayout.LayoutParams).marginEnd = dp(ctx, 8f)
        })
        addView(text(ctx, label, 15f))
        isClickable = true
        setOnClickListener { onClick() }
    }

    private fun outline(ctx: Context, radius: Float = 3f): StateListDrawable {
        fun shape(fill: Int) = GradientDrawable().apply {
            setColor(fill)
            setStroke(dp(ctx, 2f), accent)
            cornerRadius = dp(ctx, radius).toFloat()
        }
        return StateListDrawable().apply {
            addState(intArrayOf(android.R.attr.state_pressed), shape(faint))
            addState(intArrayOf(), shape(Color.TRANSPARENT))
        }
    }

    /** The placeholder brand mark (Logo.qml): "R80" in DIN in a pill. */
    fun logo(ctx: Context) = text(ctx, "R80", 15f, numbers = true).apply {
        letterSpacing = 0.2f
        setPadding(dp(ctx, 14f), dp(ctx, 2f), dp(ctx, 14f), dp(ctx, 2f))
        background = GradientDrawable().apply {
            setColor(Color.TRANSPARENT)
            setStroke(dp(ctx, 2f), accent)
            cornerRadius = dp(ctx, 20f).toFloat()
        }
    }

    /** Tabs as on the HU (Tabs.qml): the current one bright and underlined. */
    fun tabs(ctx: Context, labels: List<String>, current: Int, onSelect: (Int) -> Unit) = LinearLayout(ctx).apply {
        orientation = LinearLayout.HORIZONTAL
        labels.forEachIndexed { i, label ->
            addView(LinearLayout(ctx).apply {
                orientation = LinearLayout.VERTICAL
                setPadding(0, 0, dp(ctx, 28f), 0)
                addView(text(ctx, label, 17f, if (i == current) accent else dim).apply { setPadding(0, dp(ctx, 8f), 0, dp(ctx, 6f)) })
                addView(View(ctx).apply {
                    setBackgroundColor(if (i == current) accent else Color.TRANSPARENT)
                    layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(ctx, 3f))
                })
                isClickable = true
                setOnClickListener { onSelect(i) }
            })
        }
    }

    /** A data row as on the HU's Vehicle screen: icon, label, value (DIN) on the right, a faint line below. */
    fun dataRow(ctx: Context, iconRes: Int, label: String, value: String) = LinearLayout(ctx).apply {
        orientation = LinearLayout.VERTICAL
        addView(LinearLayout(ctx).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            minimumHeight = dp(ctx, 52f)
            addView(icon(ctx, iconRes, 26f))
            addView(text(ctx, label, 16f).apply {
                layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply { marginStart = dp(ctx, 16f) }
            })
            addView(text(ctx, value, 22f, numbers = true))
        })
        addView(line(ctx))
    }

    fun line(ctx: Context, color: Int = faint) = View(ctx).apply {
        setBackgroundColor(color)
        layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 1)
    }

    /** Gives views from an XML layout the HU look: texts, switches, buttons, fields. */
    fun style(v: View) {
        when (v) {
            is CompoundButton -> {
                v.setTextColor(accent); v.typeface = text
                v.buttonTintList = ColorStateList.valueOf(accent)
                if (v is android.widget.Switch) {
                    v.thumbTintList = ColorStateList(arrayOf(intArrayOf(android.R.attr.state_checked), intArrayOf()), intArrayOf(accent, mid))
                    v.trackTintList = ColorStateList(arrayOf(intArrayOf(android.R.attr.state_checked), intArrayOf()), intArrayOf(dim, faint))
                }
            }
            is Button -> {
                v.setTextColor(accent); v.typeface = text; v.isAllCaps = false
                v.background = outline(v.context); v.stateListAnimator = null
            }
            is EditText -> {
                v.setTextColor(accent); v.setHintTextColor(dim); v.typeface = text
                v.backgroundTintList = ColorStateList.valueOf(dim)
            }
            is TextView -> {
                v.setTextColor(if (v.tag == "title") accent else mid)
                v.typeface = if (v.tag == "title") bold else text
            }
            is ViewGroup -> for (i in 0 until v.childCount) style(v.getChildAt(i))
        }
        if (v is android.widget.Spinner) v.backgroundTintList = ColorStateList.valueOf(accent)
    }
}
