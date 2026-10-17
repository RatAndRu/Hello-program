package com.example.budgetlife

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

class BudgetStore(private val context: Context) {
    private val dir = File(context.filesDir, "budgetlife").apply { mkdirs() }
    private val stateFile = File(dir, "state.json")
    private val backupsFile = File(dir, "backups.json")
    private val historyFile = File(dir, "rates-history.json")

    fun load(): AppState {
        return try { if (stateFile.exists()) AppState.fromJson(JSONObject(stateFile.readText())) else AppState.defaults() } catch (_: Exception) { AppState.defaults() }
    }
    fun save(state: AppState) {
        state.updatedAt = System.currentTimeMillis()
        try { stateFile.writeText(state.toJson().toString()) } catch (_: Exception) { }
        dailyBackup(state)
    }
    private fun readBackups(): JSONArray = try { if (backupsFile.exists()) JSONArray(backupsFile.readText()) else JSONArray() } catch (_: Exception) { JSONArray() }
    private fun writeBackups(a: JSONArray) { try { backupsFile.writeText(a.toString()) } catch (_: Exception) { } }
    fun saveBackup(label: String, state: AppState) {
        val a = readBackups(); a.put(JSONObject().apply { put("createdAt", System.currentTimeMillis()); put("label", label); put("data", state.toJson()) })
        while (a.length() > 12) a.remove(0)
        writeBackups(a)
    }
    private fun dailyBackup(state: AppState) {
        val today = Dates.today(); val a = readBackups(); var exists = false
        for (i in 0 until a.length()) { val o = a.optJSONObject(i) ?: continue; if (o.optString("label") == "Авто $today") exists = true }
        if (!exists) saveBackup("Авто $today", state)
    }
    fun listBackups(): List<Triple<Long, Long, String>> { val a = readBackups(); return (a.length() - 1 downTo 0).map { i -> val o = a.optJSONObject(i); Triple(i.toLong(), o?.optLong("createdAt") ?: 0L, o?.optString("label") ?: "Копия") } }
    fun restoreBackup(index: Int): AppState? = try { val o = readBackups().optJSONObject(index)?.optJSONObject("data"); if (o != null) AppState.fromJson(o) else null } catch (_: Exception) { null }
    fun deleteBackup(index: Int) { val a = readBackups(); if (index in 0 until a.length()) a.remove(index); writeBackups(a) }

    fun loadRatesHistory(): MutableList<RatesSnapshot> = try { if (!historyFile.exists()) mutableListOf() else JSONArray(historyFile.readText()).objects().map { RatesSnapshot.from(it) }.toMutableList() } catch (_: Exception) { mutableListOf() }
    fun saveRatesHistory(snapshot: RatesSnapshot) { val list = loadRatesHistory(); val last = list.lastOrNull(); if (last != null && last.date == snapshot.date) list[list.lastIndex] = snapshot else list += snapshot; try { historyFile.writeText(JSONArray().also { a -> list.takeLast(120).forEach { a.put(it.toJson()) } }.toString()) } catch (_: Exception) { } }
    fun pairHistory(from: String, to: String, tail: Int = 30): List<Double> { val base = loadRatesHistory().lastOrNull()?.base ?: return emptyList(); return loadRatesHistory().takeLast(tail).mapNotNull { p -> val rf = if (from == p.base) 1.0 else p.rates[from]; val rt = if (to == p.base) 1.0 else p.rates[to]; if (rf == null || rt == null || rf == 0.0) null else rt / rf }.filter { it.isFinite() } }
}
