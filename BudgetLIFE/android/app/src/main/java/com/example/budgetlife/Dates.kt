package com.example.budgetlife

import java.time.LocalDate
import java.time.YearMonth
import java.time.format.DateTimeFormatter
import java.util.Locale

object Dates {
    val RU: Locale = Locale("ru", "RU")
    fun today(): String = LocalDate.now().toString()
    fun nowYM(): String = today().substring(0, 7)
    fun parse(s: String): LocalDate = try { LocalDate.parse(s) } catch (_: Exception) { LocalDate.now() }
    fun ymOf(date: String): String = date.substring(0, 7)
    fun addYM(ym: String, delta: Long): String = YearMonth.parse(ym).plusMonths(delta).toString()
    fun daysInMonth(y: Int, m: Int): Int = YearMonth.of(y, m).lengthOfMonth()
    fun fmt(date: String, pattern: String = "d MMM yyyy"): String = try { parse(date).format(DateTimeFormatter.ofPattern(pattern, RU)) } catch (_: Exception) { date }
    fun fmtShort(date: String): String = fmt(date, "d MMM")
    fun monthLabel(ym: String): String = try { YearMonth.parse(ym).atDay(1).format(DateTimeFormatter.ofPattern("LLLL yyyy", RU)) } catch (_: Exception) { ym }
    fun monthBounds(ym: String): Pair<String, String> { val m = YearMonth.parse(ym); return m.atDay(1).toString() to m.atEndOfMonth().toString() }
    fun dateRange(from: String, to: String): List<String> { val out = mutableListOf<String>(); var d = parse(from); val end = parse(to); while (!d.isAfter(end)) { out += d.toString(); d = d.plusDays(1) }; return out }
    fun diffDays(a: String, b: String): Long = java.time.temporal.ChronoUnit.DAYS.between(parse(a), parse(b))

    private val fixedDayOffs = setOf("01-01","01-02","01-03","01-04","01-05","01-06","01-07","01-08","02-23","03-08","05-01","05-02","05-03","05-04","05-05","05-06","05-07","05-08","05-09","06-12","11-04","12-31")
    fun isDayOff(d: LocalDate): Boolean { val wd = d.dayOfWeek.value; if (wd == 6 || wd == 7) return true; return fixedDayOffs.contains("%02d-%02d".format(d.monthValue, d.dayOfMonth)) }
    fun resolvePayDay(ym: String, day: Int, rule: String = "prevWorkday"): String {
        val m = YearMonth.parse(ym); val dim = m.lengthOfMonth(); val d = if (day > 0) minOf(day, dim) else maxOf(1, dim + 1 + day)
        var date = m.atDay(d)
        if (rule == "prevWorkday") { var g = 0; while (isDayOff(date) && g++ < 14) date = date.minusDays(1) }
        if (rule == "nextWorkday") { var g = 0; while (isDayOff(date) && g++ < 14) date = date.plusDays(1) }
        return date.toString()
    }
    fun describePayDay(day: Int): String = when (day) { -1 -> "последний день месяца"; -2 -> "предпоследний день месяца"; else -> "$day-го числа" }
    fun addCycles(date: String, every: Int, unit: String, n: Long): String { val d = parse(date); val e = maxOf(1, every).toLong() * n; return when (unit) { "day" -> d.plusDays(e).toString(); "week" -> d.plusWeeks(e).toString(); "month" -> { val t = d.plusMonths(e); t.withDayOfMonth(minOf(d.dayOfMonth, t.lengthOfMonth())).toString() }; "year" -> { val t = d.plusYears(e); t.withDayOfMonth(minOf(d.dayOfMonth, t.lengthOfMonth())).toString() }; else -> d.plusMonths(e).toString() } }
    fun cycleDays(every: Int, unit: String): Double = (when (unit) { "day" -> 1.0; "week" -> 7.0; "year" -> 365.25; else -> 30.4375 }) * maxOf(1, every)
    fun cycleLabel(every: Int, unit: String): String { val n = maxOf(1, every); val name = when (unit) { "day" -> "день"; "week" -> "неделю"; "year" -> "год"; else -> "месяц" }; return if (n == 1) when (unit) { "day" -> "ежедневно"; "week" -> "каждую неделю"; "year" -> "каждый год"; else -> "каждый месяц" } else "раз в $n $name" }
    fun financialMonthBounds(ref: String, startDay: Int): Pair<String, String> {
        val d = parse(ref); val day = startDay.coerceIn(1, YearMonth.from(d).lengthOfMonth()); val thisStart = d.withDayOfMonth(day)
        return if (!d.isBefore(thisStart)) { thisStart.toString() to thisStart.plusMonths(1).minusDays(1).toString() } else { thisStart.minusMonths(1).toString() to thisStart.minusDays(1).toString() }
    }
    fun humanRelative(iso: String): String { val diff = diffDays(today(), iso); return when { diff == 0L -> "сегодня"; diff == 1L -> "завтра"; diff == -1L -> "вчера"; diff in 2..6 -> "через $diff дн."; diff in -6..-2 -> "${-diff} дн. назад"; diff >= 7 -> "через ${diff / 7} нед."; else -> "${-diff / 7} нед. назад" } }
}
