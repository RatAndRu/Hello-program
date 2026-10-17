package com.example.budgetlife

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.graphics.drawable.GradientDrawable
import android.view.View
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import kotlin.math.max
import kotlin.math.min

data class Palette(val bg: Int, val card: Int, val card2: Int, val text: Int, val muted: Int, val line: Int, val brand: Int, val mint: Int, val rose: Int, val amber: Int)
fun palette(state: AppState): Palette = if (state.settings.theme == "light") Palette(Color.rgb(244, 247, 251), Color.WHITE, Color.rgb(232, 238, 246), Color.rgb(15, 23, 42), Color.rgb(100, 116, 139), Color.rgb(203, 213, 225), Color.rgb(2, 132, 199), Color.rgb(5, 150, 105), Color.rgb(225, 29, 72), Color.rgb(217, 119, 6)) else Palette(Color.rgb(5, 9, 20), Color.rgb(13, 20, 38), Color.rgb(18, 28, 52), Color.rgb(238, 242, 255), Color.rgb(148, 163, 184), Color.rgb(38, 52, 82), Color.rgb(56, 195, 245), Color.rgb(16, 209, 154), Color.rgb(251, 113, 133), Color.rgb(251, 191, 92))

fun Context.dp(v: Int): Int = (v * resources.displayMetrics.density).toInt()
fun Context.dp(v: Float): Int = (v * resources.displayMetrics.density).toInt()
fun rounded(color: Int, radiusDp: Int, ctx: Context, stroke: Int? = null): GradientDrawable = GradientDrawable().apply { setColor(color); cornerRadius = ctx.dp(radiusDp).toFloat(); if (stroke != null) setStroke(ctx.dp(1), stroke) }
fun gradient(ctx: Context, start: Int, end: Int): GradientDrawable = GradientDrawable(GradientDrawable.Orientation.LEFT_RIGHT, intArrayOf(start, end)).apply { cornerRadius = ctx.dp(18).toFloat() }

fun text(ctx: Context, value: String, size: Float, color: Int, bold: Boolean = false, alignCenter: Boolean = false): TextView = TextView(ctx).apply { text = value; textSize = size; setTextColor(color); if (bold) setTypeface(typeface, android.graphics.Typeface.BOLD); if (alignCenter) gravity = android.view.Gravity.CENTER; setLineSpacing(0f, 1.08f) }
fun card(ctx: Context, pal: Palette): LinearLayout = LinearLayout(ctx).apply { orientation = LinearLayout.VERTICAL; background = rounded(pal.card, 20, ctx, pal.line); setPadding(ctx.dp(16), ctx.dp(14), ctx.dp(16), ctx.dp(14)); val lp = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT); lp.setMargins(0, 0, 0, ctx.dp(12)); layoutParams = lp }
fun row(ctx: Context): LinearLayout = LinearLayout(ctx).apply { orientation = LinearLayout.HORIZONTAL; gravity = android.view.Gravity.CENTER_VERTICAL }
fun spacer(ctx: Context, weight: Float = 1f): View = View(ctx).apply { layoutParams = LinearLayout.LayoutParams(0, 1, weight) }
fun vspace(ctx: Context, h: Int): View = View(ctx).apply { layoutParams = LinearLayout.LayoutParams(1, ctx.dp(h)) }
fun actionButton(ctx: Context, pal: Palette, label: String, primary: Boolean = false, danger: Boolean = false): Button = Button(ctx).apply { text = label; textSize = 13f; isAllCaps = false; setTextColor(if (primary) Color.rgb(4, 18, 30) else if (danger) pal.rose else pal.text); background = if (primary) gradient(ctx, pal.brand, pal.mint) else rounded(pal.card2, 14, ctx, pal.line); setPadding(ctx.dp(12), ctx.dp(8), ctx.dp(12), ctx.dp(8)) }
fun chip(ctx: Context, pal: Palette, label: String, selected: Boolean): Button = Button(ctx).apply { text = label; textSize = 12f; isAllCaps = false; setTextColor(if (selected) Color.rgb(4, 18, 30) else pal.muted); background = if (selected) gradient(ctx, pal.brand, pal.mint) else rounded(pal.card2, 999, ctx, pal.line); setPadding(ctx.dp(11), ctx.dp(6), ctx.dp(11), ctx.dp(6)); layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply { setMargins(0, 0, ctx.dp(7), 0) } }
fun progress(ctx: Context, pal: Palette, fraction: Double, color: Int): View { val outer = LinearLayout(ctx).apply { background = rounded(Color.argb(55, Color.red(pal.muted), Color.green(pal.muted), Color.blue(pal.muted)), 999, ctx); layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, ctx.dp(8)) }; val inner = View(ctx).apply { background = rounded(color, 999, ctx); layoutParams = LinearLayout.LayoutParams((ctx.dp(280) * fraction.coerceIn(0.0, 1.0)).toInt().coerceAtLeast(if (fraction > 0) ctx.dp(8) else 0), LinearLayout.LayoutParams.MATCH_PARENT) }; outer.addView(inner); return outer }

class LineChartView(ctx: Context, private val values: List<Double>, private val labels: List<String>, private val pal: Palette, private val lineColor: Int) : View(ctx) {
    private fun dp(v: Number): Int = (v.toFloat() * resources.displayMetrics.density).toInt()
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG); private val txt = Paint(Paint.ANTI_ALIAS_FLAG).apply { textSize = ctx.dp(10).toFloat(); color = pal.muted }
    override fun onDraw(canvas: Canvas) { super.onDraw(canvas); if (values.isEmpty()) return; val pad = dp(12).toFloat(); val w = width - pad * 2; val h = height - dp(28).toFloat(); val minV = values.minOrNull() ?: 0.0; val maxV = values.maxOrNull() ?: 0.0; val range = max(1.0, maxV - minV); paint.color = pal.line; paint.strokeWidth = dp(1).toFloat(); for (i in 0..3) { val y = pad + h * i / 3; canvas.drawLine(pad, y, width - pad, y, paint) }; val path = Path(); values.forEachIndexed { i, v -> val x = pad + if (values.size == 1) w / 2 else w * i / (values.size - 1); val y = pad + h - ((v - minV) / range * h).toFloat(); if (i == 0) path.moveTo(x, y) else path.lineTo(x, y) }; paint.color = Color.argb(45, Color.red(lineColor), Color.green(lineColor), Color.blue(lineColor)); paint.style = Paint.Style.FILL; val fill = Path(path); fill.lineTo(width - pad, pad + h); fill.lineTo(pad, pad + h); fill.close(); canvas.drawPath(fill, paint); paint.style = Paint.Style.STROKE; paint.color = lineColor; paint.strokeWidth = dp(2.4f).toFloat(); canvas.drawPath(path, paint); paint.style = Paint.Style.FILL; values.forEachIndexed { i, v -> val x = pad + if (values.size == 1) w / 2 else w * i / (values.size - 1); val y = pad + h - ((v - minV) / range * h).toFloat(); canvas.drawCircle(x, y, dp(3).toFloat(), paint); if (i % max(1, values.size / 5) == 0 || i == values.lastIndex) canvas.drawText(labels.getOrElse(i) { "" }, x - dp(14), height - dp(6).toFloat(), txt) } }
}

class MonthlyBarsView(ctx: Context, private val income: List<Double>, private val expense: List<Double>, private val labels: List<String>, private val pal: Palette) : View(ctx) {
    private fun dp(v: Number): Int = (v.toFloat() * resources.displayMetrics.density).toInt()
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG); private val txt = Paint(Paint.ANTI_ALIAS_FLAG).apply { textSize = ctx.dp(9).toFloat(); color = pal.muted }
    override fun onDraw(canvas: Canvas) { super.onDraw(canvas); if (income.isEmpty()) return; val maxV = max(1.0, max(income.maxOrNull() ?: 0.0, expense.maxOrNull() ?: 0.0)); val chartH = height - dp(30).toFloat(); val slot = width.toFloat() / income.size; val bw = min(dp(13).toFloat(), slot / 4); income.indices.forEach { i -> val cx = slot * i + slot / 2; val ih = (income[i] / maxV * chartH).toFloat(); val eh = (expense[i] / maxV * chartH).toFloat(); paint.color = pal.mint; canvas.drawRoundRect(cx - bw - dp(2), chartH - ih, cx - dp(2).toFloat(), chartH, dp(3).toFloat(), dp(3).toFloat(), paint); paint.color = pal.rose; canvas.drawRoundRect(cx + dp(2).toFloat(), chartH - eh, cx + bw + dp(2), chartH, dp(3).toFloat(), dp(3).toFloat(), paint); if (i % max(1, income.size / 6) == 0) canvas.drawText(labels.getOrElse(i) { "" }, cx - dp(12), height - dp(7).toFloat(), txt) } }
}

data class CalendarCellData(val date: String, val inMonth: Boolean, val isToday: Boolean, val income: Double, val expense: Double, val count: Int)
class CalendarView(ctx: Context, private val cells: List<CalendarCellData>, private val pal: Palette, private val fmt: (Double) -> String, private val onSelect: (String) -> Unit) : View(ctx) {
    private fun dp(v: Number): Int = (v.toFloat() * resources.displayMetrics.density).toInt()
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG); private val txt = Paint(Paint.ANTI_ALIAS_FLAG).apply { textAlign = Paint.Align.CENTER }
    private var selected: String? = null
    fun select(date: String) { selected = date; invalidate() }
    override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) { val w = MeasureSpec.getSize(widthMeasureSpec); setMeasuredDimension(w, (w / 7f * 6.15f).toInt()) }
    override fun onDraw(canvas: Canvas) { super.onDraw(canvas); if (cells.isEmpty()) return; val cw = width / 7f; val ch = height / 6f; cells.forEachIndexed { idx, cell -> val x = (idx % 7) * cw; val y = (idx / 7) * ch; if (cell.date == selected) { paint.color = Color.argb(55, Color.red(pal.brand), Color.green(pal.brand), Color.blue(pal.brand)); canvas.drawRoundRect(x + 2, y + 2, x + cw - 2, y + ch - 2, dp(10).toFloat(), dp(10).toFloat(), paint) } else if (cell.isToday) { paint.color = Color.argb(30, Color.red(pal.mint), Color.green(pal.mint), Color.blue(pal.mint)); canvas.drawRoundRect(x + 2, y + 2, x + cw - 2, y + ch - 2, dp(10).toFloat(), dp(10).toFloat(), paint) }; txt.color = if (cell.inMonth) pal.text else pal.muted; txt.textSize = dp(12).toFloat(); txt.typeface = android.graphics.Typeface.DEFAULT_BOLD; canvas.drawText(Dates.parse(cell.date).dayOfMonth.toString(), x + cw / 2, y + dp(17), txt); txt.typeface = android.graphics.Typeface.DEFAULT; txt.textSize = dp(7.5f).toFloat(); if (cell.income > 0) { txt.color = pal.mint; canvas.drawText(fmt(cell.income), x + cw / 2, y + ch - dp(18), txt) }; if (cell.expense > 0) { txt.color = pal.rose; canvas.drawText(fmt(cell.expense), x + cw / 2, y + ch - dp(7), txt) }; if (cell.count > 0 && cell.income == 0.0 && cell.expense == 0.0) { paint.color = pal.brand; canvas.drawCircle(x + cw / 2, y + ch - dp(10), dp(2.2f).toFloat(), paint) } } }
    override fun onTouchEvent(event: android.view.MotionEvent): Boolean { if (event.action == android.view.MotionEvent.ACTION_UP) { val col = (event.x / (width / 7f)).toInt().coerceIn(0, 6); val rowIdx = (event.y / (height / 6f)).toInt().coerceIn(0, 5); val cell = cells.getOrNull(rowIdx * 7 + col); if (cell != null) { select(cell.date); onSelect(cell.date); return true } }; return true }
}
