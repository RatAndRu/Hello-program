package com.example.bluelink

import android.content.Context
import android.content.res.ColorStateList
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.RippleDrawable
import android.text.InputType
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView

/** Палитра приложения. */
object Pal {
    val BG = 0xFF0B0F14.toInt()
    val SURFACE = 0xFF131A22.toInt()
    val SURFACE_2 = 0xFF1B242F.toInt()
    val TEXT = 0xFFE6EDF3.toInt()
    val MUTED = 0xFF8FA3B8.toInt()
    val ACCENT = 0xFF38BDF8.toInt()
    val ACCENT_DARK = 0xFF0284C7.toInt()
    val VIOLET = 0xFFA78BFA.toInt()
    val GREEN = 0xFF34D399.toInt()
    val RED = 0xFFF87171.toInt()
    val AMBER = 0xFFFBBF24.toInt()
    val STROKE = 0xFF243040.toInt()
}

fun Context.dp(v: Number): Int = (v.toFloat() * resources.displayMetrics.density + 0.5f).toInt()

fun Context.roundRect(fill: Int, radiusDp: Number, stroke: Int? = null, strokeDp: Number = 1): GradientDrawable {
    val d = GradientDrawable()
    d.shape = GradientDrawable.RECTANGLE
    d.cornerRadius = dp(radiusDp).toFloat()
    d.setColor(fill)
    if (stroke != null) d.setStroke(dp(strokeDp), stroke)
    return d
}

fun Context.tappable(fill: Int, radiusDp: Number, stroke: Int? = null): RippleDrawable {
    val bg = roundRect(fill, radiusDp, stroke)
    return RippleDrawable(ColorStateList.valueOf(0x33FFFFFF), bg, null)
}

/** Вертикальный контейнер. */
fun Context.column(padDp: Int = 0): LinearLayout {
    val l = LinearLayout(this)
    l.orientation = LinearLayout.VERTICAL
    if (padDp > 0) l.setPadding(dp(padDp), dp(padDp), dp(padDp), dp(padDp))
    return l
}

/** Горизонтальный контейнер, элементы по центру по вертикали. */
fun Context.row(): LinearLayout {
    val l = LinearLayout(this)
    l.orientation = LinearLayout.HORIZONTAL
    l.gravity = Gravity.CENTER_VERTICAL
    return l
}

fun Context.txt(
    text: CharSequence,
    sizeSp: Number = 14,
    color: Int = Pal.TEXT,
    bold: Boolean = false,
    mono: Boolean = false
): TextView {
    val t = TextView(this)
    t.text = text
    t.setTextColor(color)
    t.setTextSize(android.util.TypedValue.COMPLEX_UNIT_SP, sizeSp.toFloat())
    if (bold) t.setTypeface(Typeface.DEFAULT_BOLD)
    if (mono) t.typeface = Typeface.MONOSPACE
    t.setLineSpacing(dp(2).toFloat(), 1f)
    return t
}

fun Context.spacer(hDp: Number): View {
    val v = View(this)
    v.layoutParams = LinearLayout.LayoutParams(1, dp(hDp))
    return v
}

fun Context.hspace(wDp: Number): View {
    val v = View(this)
    v.layoutParams = LinearLayout.LayoutParams(dp(wDp), 1)
    return v
}

fun Context.divider(color: Int = Pal.STROKE): View {
    val v = View(this)
    v.setBackgroundColor(color)
    v.layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(1))
    return v
}

/** Карточка с мягким фоном. */
fun Context.card(padDp: Int = 14): LinearLayout {
    val l = column()
    l.background = roundRect(Pal.SURFACE, 16, Pal.STROKE)
    l.setPadding(dp(padDp), dp(padDp), dp(padDp), dp(padDp))
    l.layoutParams = LinearLayout.LayoutParams(
        LinearLayout.LayoutParams.MATCH_PARENT,
        LinearLayout.LayoutParams.WRAP_CONTENT
    ).apply { bottomMargin = dp(10) }
    return l
}

/** Маленькая «таблетка» — фильтр/чип. */
fun Context.pill(text: String, active: Boolean, onClick: () -> Unit): TextView {
    val t = txt(text, 13, if (active) 0xFF04222F.toInt() else Pal.TEXT, bold = active)
    t.gravity = Gravity.CENTER
    t.setPadding(dp(14), dp(8), dp(14), dp(8))
    t.background = tappable(
        if (active) Pal.ACCENT else Pal.SURFACE_2, 999,
        if (active) null else Pal.STROKE
    )
    t.isClickable = true
    t.isFocusable = true
    t.setOnClickListener { onClick() }
    val lp = LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT)
    lp.rightMargin = dp(8)
    t.layoutParams = lp
    return t
}

/** Основная кнопка (primary) или вторичная. */
fun Context.actionButton(text: String, primary: Boolean = true, onClick: () -> Unit): Button {
    val b = Button(this)
    b.text = text
    b.isAllCaps = false
    b.setTextSize(android.util.TypedValue.COMPLEX_UNIT_SP, 14f)
    b.typeface = Typeface.DEFAULT_BOLD
    b.setTextColor(if (primary) 0xFF04222F.toInt() else Pal.TEXT)
    b.background = tappable(
        if (primary) Pal.ACCENT else Pal.SURFACE_2, 999,
        if (primary) null else Pal.STROKE
    )
    b.stateListAnimator = null
    b.minWidth = 0
    b.minimumWidth = 0
    b.minimumHeight = 0
    b.setPadding(dp(18), dp(10), dp(18), dp(10))
    b.isAllCaps = false
    b.setOnClickListener { onClick() }
    val lp = LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, dp(44))
    lp.rightMargin = dp(8)
    b.layoutParams = lp
    return b
}

fun Context.input(hint: String, value: String = "", multiline: Boolean = false): EditText {
    val e = EditText(this)
    e.hint = hint
    e.setText(value)
    e.setTextColor(Pal.TEXT)
    e.setHintTextColor(Pal.MUTED)
    e.setTextSize(android.util.TypedValue.COMPLEX_UNIT_SP, 13f)
    e.background = roundRect(Pal.BG, 12, Pal.STROKE)
    e.setPadding(dp(12), dp(10), dp(12), dp(10))
    e.isSingleLine = !multiline
    if (multiline) {
        e.inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_MULTI_LINE
        e.minLines = 3
    }
    val lp = LinearLayout.LayoutParams(
        LinearLayout.LayoutParams.MATCH_PARENT,
        LinearLayout.LayoutParams.WRAP_CONTENT
    )
    lp.bottomMargin = dp(8)
    e.layoutParams = lp
    return e
}

fun Context.badge(text: String, color: Int = Pal.MUTED): TextView {
    val t = txt(text, 11, color, bold = true)
    t.setPadding(dp(8), dp(3), dp(8), dp(3))
    t.background = roundRect(ColorUtils.withAlpha(color, 0x22), 999)
    t.layoutParams = LinearLayout.LayoutParams(
        LinearLayout.LayoutParams.WRAP_CONTENT,
        LinearLayout.LayoutParams.WRAP_CONTENT
    ).apply { rightMargin = dp(6) }
    return t
}

object ColorUtils {
    fun withAlpha(color: Int, alpha: Int): Int =
        (color and 0x00FFFFFF) or ((alpha and 0xFF) shl 24)
}
