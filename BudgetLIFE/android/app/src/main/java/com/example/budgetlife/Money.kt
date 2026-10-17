package com.example.budgetlife

import java.text.NumberFormat
import java.util.Locale

object CurrencyInfo {
    val options = listOf(
        Triple("RUB", "Российский рубль", "₽"), Triple("USD", "Доллар США", "$"), Triple("EUR", "Евро", "€"), Triple("CNY", "Китайский юань", "¥"), Triple("GBP", "Фунт стерлингов", "£"), Triple("JPY", "Японская иена", "¥"), Triple("CHF", "Швейцарский франк", "Fr"), Triple("KZT", "Казахстанский тенге", "₸"), Triple("BYN", "Белорусский рубль", "Br"), Triple("TRY", "Турецкая лира", "₺"), Triple("AED", "Дирхам ОАЭ", "د.إ"), Triple("INR", "Индийская рупия", "₹"), Triple("KRW", "Вон Республики Корея", "₩"), Triple("AMD", "Армянский драм", "֏"), Triple("GEL", "Грузинский лари", "₾"), Triple("UZS", "Узбекский сум", "soʻm"), Triple("PLN", "Польский злотый", "zł"), Triple("CZK", "Чешская крона", "Kč"), Triple("SEK", "Шведская крона", "kr"), Triple("NOK", "Норвежская крона", "kr"), Triple("CAD", "Канадский доллар", "C$"), Triple("AUD", "Австралийский доллар", "A$"), Triple("SGD", "Сингапурский доллар", "S$"), Triple("HKD", "Гонконгский доллар", "HK$"), Triple("THB", "Тайский бат", "฿"), Triple("BTC", "Биткоин", "₿"), Triple("ETH", "Эфириум", "Ξ"), Triple("USDT", "Tether", "₮")
    )
    val codes: List<String> get() = options.map { it.first }
    fun symbol(code: String): String = options.firstOrNull { it.first == code }?.third ?: code
    fun decimals(code: String, showCents: Boolean): Int { if (!showCents) return 0; return when (code) { "JPY", "KRW", "UZS" -> 0; "BTC", "ETH" -> 6; else -> 2 } }
}

object Money {
    fun parse(input: String?): Double = input?.replace("\u00A0", "").replace(" ", "").replace(",", ".")?.toDoubleOrNull() ?: 0.0
    fun input(v: Double?): String = if (v == null || v == 0.0) "" else round2(v).toString().replace('.', ',').trimEnd('0').trimEnd(',')
    fun fmt(amount: Double, currency: String, state: AppState? = null, signed: Boolean = false, compact: Boolean = false): String {
        if (state?.settings?.hideBalances == true) return "••••••"
        if (!amount.isFinite()) return "—"
        if (compact) {
            val abs = kotlin.math.abs(amount); val sign = if (amount < 0) "−" else if (signed) "+" else ""
            val units = listOf(1e12 to "трлн", 1e9 to "млрд", 1e6 to "млн", 1e3 to "тыс.")
            for ((mul, name) in units) if (abs >= mul) { val v = abs / mul; return "$sign${String.format(Locale("ru"), if (v >= 100) "%.0f" else if (v >= 10) "%.1f" else "%.2f", v).trimEnd('0').trimEnd(',')} $name ${CurrencyInfo.symbol(currency)}" }
        }
        val cents = state?.settings?.showCents ?: true
        val d = CurrencyInfo.decimals(currency, cents)
        val nf = NumberFormat.getNumberInstance(Locale("ru", "RU")).apply { minimumFractionDigits = d; maximumFractionDigits = d }
        val sign = if (amount < 0) "−" else if (signed) "+" else ""
        return "$sign${nf.format(kotlin.math.abs(amount))} ${CurrencyInfo.symbol(currency)}"
    }
    fun percent(v: Double, digits: Int = 1): String = "${String.format(Locale("ru"), "%.${digits}f", v)} %"
}

object RatesMath {
    fun rateOf(currency: String, state: AppState): Double? {
        if (currency == state.settings.baseCurrency) return 1.0
        state.settings.manualRates[currency]?.takeIf { it > 0 }?.let { return it }
        val v = state.rates?.rates?.get(currency)
        return v?.takeIf { it.isFinite() && it > 0 }
    }
    fun convert(amount: Double, from: String, to: String, state: AppState): Double {
        if (!amount.isFinite() || from == to) return amount
        val rf = rateOf(from, state) ?: return amount
        val rt = rateOf(to, state) ?: return amount
        return amount / rf * rt
    }
    fun hasRate(from: String, to: String, state: AppState): Boolean = from == to || (rateOf(from, state) != null && rateOf(to, state) != null)
    fun rebase(rates: Map<String, Double>, fromBase: String, toBase: String): Map<String, Double>? {
        if (fromBase == toBase) return rates + (toBase to 1.0)
        val k = rates[toBase]?.takeIf { it != 0.0 } ?: return null
        return rates.mapValues { it.value / k } + (toBase to 1.0)
    }
}
