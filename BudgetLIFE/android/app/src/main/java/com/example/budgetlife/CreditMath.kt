package com.example.budgetlife

import kotlin.math.pow

data class ScheduleRow(val index: Int, val date: String, val payment: Double, val interest: Double, val principal: Double, val balance: Double)

object CreditMath {
    fun monthlyRate(annualRate: Double) = annualRate / 100.0 / 12.0
    fun annuity(principal: Double, annualRate: Double, months: Int): Double { if (months <= 0) return 0.0; val r = monthlyRate(annualRate); if (r == 0.0) return principal / months; val k = (1 + r).pow(months); return principal * r * k / (k - 1) }
    fun monthsElapsed(startDate: String, ref: String = Dates.today()): Int { val s = Dates.parse(startDate); val e = Dates.parse(ref); var m = (e.year - s.year) * 12 + (e.monthValue - s.monthValue); if (e.dayOfMonth < s.dayOfMonth) m--; return maxOf(0, m) }
    fun nextPaymentDate(startDate: String, paymentDay: Int, offsetMonths: Long): String { val s = Dates.parse(startDate); val d = s.withDayOfMonth(1).plusMonths(offsetMonths); val dim = d.lengthOfMonth(); return d.withDayOfMonth(minOf(if (paymentDay > 0) paymentDay else dim, dim)).toString() }

    fun loanSchedule(credit: Credit): List<ScheduleRow> {
        if (credit.termMonths <= 0) return emptyList()
        val elapsed = monthsElapsed(credit.startDate)
        val paidMonths = if (credit.currentBalance != null) minOf(credit.termMonths, elapsed + 1) else 0
        val remaining = maxOf(1, credit.termMonths - paidMonths)
        var balance = credit.currentBalance ?: credit.principal
        if (balance <= 0) return emptyList()
        val r = monthlyRate(credit.annualRate); val fixedPrincipal = credit.principal / credit.termMonths
        val ann = annuity(balance, credit.annualRate, remaining)
        val rows = mutableListOf<ScheduleRow>()
        for (i in 1..remaining) {
            val date = nextPaymentDate(credit.startDate, credit.paymentDay, (paidMonths + i).toLong())
            val interest = balance * r
            var principalPart: Double; var payment: Double
            if (credit.paymentType == "differentiated") { principalPart = minOf(fixedPrincipal, balance); payment = principalPart + interest } else { payment = ann; principalPart = minOf(payment - interest, balance); if (principalPart <= 0) principalPart = minOf(payment, balance) }
            if (i == remaining || balance - principalPart < 0.01) { principalPart = balance; payment = principalPart + interest }
            balance = maxOf(0.0, balance - principalPart)
            rows += ScheduleRow(paidMonths + i, date, payment, interest, principalPart, balance)
            if (balance <= 0) break
        }
        return rows
    }

    fun statementDate(ym: String, day: Int): String { val m = java.time.YearMonth.parse(ym); return m.atDay(minOf(day, m.lengthOfMonth())).toString() }
    fun graceEndDate(credit: Credit, statement: String): String { val graceDay = credit.gracePaymentDay; if (graceDay != null) { val d = Dates.parse(statement); return d.withDayOfMonth(minOf(graceDay, d.lengthOfMonth())).toString() }; return Dates.parse(statement).plusDays((credit.graceDays ?: 0).toLong()).toString() }
    fun cardPaymentDate(credit: Credit, ym: String): String {
        val m = java.time.YearMonth.parse(ym)
        val graceDay = credit.gracePaymentDay; val statementDay = credit.statementDay
        if (graceDay != null) { val date = m.atDay(minOf(graceDay, m.lengthOfMonth())); return if (statementDay != null && graceDay <= statementDay) date.plusMonths(1).toString() else date.toString() }
        if (statementDay != null) return graceEndDate(credit, statementDate(ym, statementDay))
        return Dates.resolvePayDay(ym, 15, "prevWorkday")
    }
    fun minPayment(credit: Credit, debt: Double = credit.used ?: 0.0): Double = maxOf(credit.minPaymentFixed ?: 0.0, debt * (credit.minPaymentPercent ?: 5.0) / 100.0)
    data class GraceInfo(val statementDate: String, val paymentDate: String, val daysLeft: Long, val debt: Double)
    fun graceInfo(credit: Credit, ref: String = Dates.today()): GraceInfo? {
        if (credit.kind != "credit_card" || credit.graceDays == null) return null
        var ym = Dates.ymOf(ref); var paymentDate = cardPaymentDate(credit, ym); var g = 0
        while (paymentDate < ref && g++ < 14) { ym = Dates.addYM(ym, 1); paymentDate = cardPaymentDate(credit, ym) }
        val statement = statementDate(ym, credit.statementDay ?: 1)
        return GraceInfo(if (statement < ref) statementDate(Dates.addYM(ym, 1), credit.statementDay ?: 1) else statement, paymentDate, Dates.diffDays(ref, paymentDate), credit.used ?: 0.0)
    }
    data class CardRow(val date: String, val payment: Double, val interest: Double, val principal: Double, val debt: Double)
    fun cardSchedule(credit: Credit, from: String, to: String): List<CardRow> {
        if (credit.kind != "credit_card") return emptyList(); var debt = credit.used ?: 0.0; if (debt <= 0) return emptyList()
        val rows = mutableListOf<CardRow>(); var ym = Dates.ymOf(from); var guard = 0
        while (ym <= Dates.ymOf(to) && guard++ < 600) { val date = cardPaymentDate(credit, ym); if (date in from..to && debt > 0.009) { val interest = if (credit.repayMode == "full") 0.0 else debt * monthlyRate(credit.annualRate); var payment = when (credit.repayMode) { "full" -> debt; "custom" -> minOf(credit.customRepayAmount ?: 0.0, debt + interest); else -> minPayment(credit, debt) }; payment = minOf(payment, debt + interest); val principal = maxOf(0.0, payment - interest); debt = maxOf(0.0, debt - principal); rows += CardRow(date, payment, interest, principal, debt) }; ym = Dates.addYM(ym, 1) }
        return rows
    }
}
