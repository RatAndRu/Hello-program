package com.example.budgetlife

import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import kotlin.concurrent.thread

/** Те же провайдеры, что и в PWA: ЦБ РФ, Frankfurter/ЕЦБ, ExchangeRate API, jsDelivr CDN + CoinGecko. */
object RatesApi {
    data class Result(val snapshot: RatesSnapshot, val tried: List<String>)
    private fun getJson(url: String, timeoutMs: Int = 9000): JSONObject {
        val c = URL(url).openConnection() as HttpURLConnection
        c.connectTimeout = timeoutMs; c.readTimeout = timeoutMs; c.requestMethod = "GET"; c.setRequestProperty("Accept", "application/json"); c.setRequestProperty("User-Agent", "BudgetLIFE Android")
        try { val code = c.responseCode; val stream = if (code in 200..299) c.inputStream else c.errorStream; val text = stream?.bufferedReader()?.use { it.readText() } ?: ""; if (code !in 200..299) throw IllegalStateException("HTTP $code"); return JSONObject(text) } finally { c.disconnect() }
    }

    private fun cbr(base: String): RatesSnapshot { val data = getJson("https://www.cbr-xml-daily.ru/daily_json.js"); val rates = mutableMapOf<String, Double>("RUB" to 1.0); val v = data.optJSONObject("Valute"); v?.keys()?.forEach { k -> val o = v.optJSONObject(k); if (o != null) rates[o.optString("CharCode", k)] = o.optDouble("Value") / maxOf(1, o.optInt("Nominal", 1)).toDouble() }; val final = RatesMath.rebase(rates, "RUB", base) ?: throw IllegalStateException("ЦБ РФ не отдаёт базовую валюту"); return RatesSnapshot("cbr", base, data.optString("Date").take(10).ifBlank { Dates.today() }, System.currentTimeMillis(), final.toMutableMap()) }
    private fun ecb(base: String): RatesSnapshot { val data = getJson("https://api.frankfurter.app/latest?from=$base"); val rates = mutableMapOf<String, Double>(); val r = data.optJSONObject("rates"); r?.keys()?.forEach { rates[it] = r.optDouble(it) }; rates[base] = 1.0; return RatesSnapshot("ecb", base, data.optString("date", Dates.today()), System.currentTimeMillis(), rates) }
    private fun erapi(base: String): RatesSnapshot { val data = getJson("https://open.er-api.com/v6/latest/$base"); if (data.optString("result") != "success") throw IllegalStateException("er-api: ${data.optString("result")}"); val rates = mutableMapOf<String, Double>(); val r = data.optJSONObject("rates"); r?.keys()?.forEach { rates[it] = r.optDouble(it) }; rates[base] = 1.0; return RatesSnapshot("erapi", base, Dates.today(), System.currentTimeMillis(), rates) }
    private fun jsdelivr(base: String): RatesSnapshot { val data = getJson("https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/${base.lowercase()}.json"); val node = data.optJSONObject(base.lowercase()) ?: throw IllegalStateException("currency-api: нет данных"); val rates = mutableMapOf<String, Double>(); node.keys().forEach { rates[it.uppercase()] = node.optDouble(it) }; rates[base] = 1.0; return RatesSnapshot("jsdelivr", base, data.optString("date", Dates.today()), System.currentTimeMillis(), rates) }
    private fun crypto(base: String, rates: MutableMap<String, Double>) { try { val data = getJson("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum,tether&vs_currencies=usd,eur,rub", 7000); val vs = base.lowercase(); mapOf("bitcoin" to "BTC", "ethereum" to "ETH", "tether" to "USDT").forEach { (id, code) -> val v = data.optJSONObject(id)?.optDouble(vs, Double.NaN) ?: Double.NaN; if (v.isFinite() && v != 0.0) rates[code] = 1.0 / v }; } catch (_: Exception) { } }

    /**
     * ВАЖНО про семантику CoinGecko в исходной PWA: там в rates[BTC] клалось «сколько base за 1 BTC».
     * В остальной системе rates[X] = «сколько X за 1 base», поэтому здесь храним обратные значения,
     * чтобы конвертер и сводки считали BTC одинаково с фиатными валютами.
     */
    fun fetch(provider: String, base: String): Result {
        val order = if (provider == "auto" || provider == "manual") { if (base == "RUB") listOf("cbr", "erapi", "jsdelivr", "ecb") else listOf("erapi", "jsdelivr", "ecb", "cbr") } else listOf(provider)
        val tried = mutableListOf<String>(); var last: Exception? = null
        for (p in order) { try { val snap = when (p) { "cbr" -> cbr(base); "ecb" -> ecb(base); "erapi" -> erapi(base); else -> jsdelivr(base) }; crypto(base, snap.rates); tried += "$p: ok"; return Result(snap, tried) } catch (e: Exception) { tried += "$p: ${e.message ?: "ошибка"}"; last = e } }
        throw IllegalStateException(last?.message ?: "Не удалось получить курсы валют. Попытки: ${tried.joinToString("; ")}")
    }

    fun refreshAsync(state: AppState, onDone: (RatesSnapshot?, String?) -> Unit) {
        if (state.settings.ratesProvider == "manual") { onDone(null, null); return }
        val provider = state.settings.ratesProvider; val base = state.settings.baseCurrency
        thread(name = "budgetlife-rates") { try { val r = fetch(provider, base); onDone(r.snapshot, r.tried.filterNot { it.endsWith("ok") }.takeIf { it.isNotEmpty() }?.joinToString("; ")) } catch (e: Exception) { onDone(null, e.message) } }
    }
}
