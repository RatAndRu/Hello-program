package com.example.bluelink

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.UUID

/**
 * Описание того, как общаться с конкретным устройством.
 * Профиль — это просто JSON: его можно импортировать, экспортировать и править в приложении.
 */
data class CameraSpec(
    val mode: String = "demo",          // demo | ble | http
    val label: String = "Сделать снимок",
    val service: UUID? = null,
    val triggerChar: UUID? = null,
    val dataChar: UUID? = null,
    val trigger: ByteArray = byteArrayOf(0x01),
    val framing: String = "jpeg",       // jpeg | sizeHeader
    val httpUrl: String = "",
    val wifiSsid: String = "",
    val wifiPassword: String = "",
    val waitMs: Int = 1200,
    val demoAsset: String = "demo/glasses_photo.jpg"
)

data class DeviceProfile(
    val id: String,
    val name: String,
    val vendor: String = "",
    val description: String = "",
    val namePrefixes: List<String> = emptyList(),
    val serviceUuids: List<UUID> = emptyList(),
    val capabilities: List<String> = listOf("battery", "device_info"),
    val batteryService: UUID? = null,
    val batteryChar: UUID? = null,
    val camera: CameraSpec? = null,
    val notes: List<String> = emptyList(),
    val builtIn: Boolean = false,
    /** Профиль создан автоматически по данным GATT, а не выбран вручную. */
    val auto: Boolean = false,
    /** Варианты камеры, угаданные по GATT (запись + уведомления в одном сервисе). */
    val cameraCandidates: List<CameraSpec> = emptyList()
) {
    val hasCamera: Boolean get() = camera != null
    val cameraModeText: String
        get() = when (camera?.mode) {
            "demo" -> "демо-камера"
            "ble" -> "камера по BLE"
            "http" -> "камера по Wi-Fi"
            else -> "нет камеры"
        }

    /** Чем больше баллов, тем лучше профиль подходит найденному устройству. */
    fun scoreFor(item: ScanItem): Int {
        if (item.demo && id == "demo_glasses") return 100
        if (item.demo) return 0
        val name = item.label.lowercase()
        var score = 0
        for (p in namePrefixes) {
            if (p.isBlank()) continue
            if (name.startsWith(p.lowercase())) score += 60 else if (name.contains(p.lowercase())) score += 40
        }
        for (u in serviceUuids) {
            if (item.serviceUuids.any { it == u }) score += 30
        }
        return score
    }

    fun toJson(): JSONObject {
        val o = JSONObject()
        o.put("id", id)
        o.put("name", name)
        o.put("vendor", vendor)
        o.put("description", description)
        o.put("capabilities", JSONArray(capabilities))
        if (namePrefixes.isNotEmpty()) o.put("match", JSONObject().apply {
            put("namePrefixes", JSONArray(namePrefixes))
            if (serviceUuids.isNotEmpty()) put("serviceUuids", JSONArray(serviceUuids.map { it.toString() }))
        })
        val battery = JSONObject()
        batteryService?.let { battery.put("service", shortOrFull(it)) }
        batteryChar?.let { battery.put("characteristic", shortOrFull(it)) }
        if (battery.length() > 0) o.put("battery", battery)
        camera?.let { c ->
            o.put("camera", JSONObject().apply {
                put("mode", c.mode)
                put("label", c.label)
                c.service?.let { put("service", shortOrFull(it)) }
                c.triggerChar?.let { put("triggerCharacteristic", shortOrFull(it)) }
                c.dataChar?.let { put("dataCharacteristic", shortOrFull(it)) }
                put("trigger", bytesToHex(c.trigger))
                put("framing", c.framing)
                if (c.httpUrl.isNotBlank()) put("httpUrl", c.httpUrl)
                if (c.wifiSsid.isNotBlank()) put("wifiSsid", c.wifiSsid)
                if (c.wifiPassword.isNotBlank()) put("wifiPassword", c.wifiPassword)
                put("waitMs", c.waitMs)
                if (c.demoAsset.isNotBlank()) put("demoAsset", c.demoAsset)
            })
        }
        if (notes.isNotEmpty()) o.put("notes", JSONArray(notes))
        if (auto) o.put("auto", true)
        if (cameraCandidates.isNotEmpty()) {
            o.put("cameraCandidates", JSONArray(cameraCandidates.map { cameraToJson(it) }))
        }
        return o
    }
}

private fun cameraToJson(c: CameraSpec): JSONObject = JSONObject().apply {
    put("mode", c.mode)
    put("label", c.label)
    c.service?.let { put("service", shortOrFull(it)) }
    c.triggerChar?.let { put("triggerCharacteristic", shortOrFull(it)) }
    c.dataChar?.let { put("dataCharacteristic", shortOrFull(it)) }
    put("trigger", bytesToHex(c.trigger))
    put("framing", c.framing)
    if (c.httpUrl.isNotBlank()) put("httpUrl", c.httpUrl)
    if (c.wifiSsid.isNotBlank()) put("wifiSsid", c.wifiSsid)
    put("waitMs", c.waitMs)
}

private fun shortOrFull(uuid: UUID): String {
    val code = GattNames.shortCode(uuid)
    return if (code != null) String.format("%04x", code) else uuid.toString()
}

object ProfileParser {

    fun parse(o: JSONObject, builtIn: Boolean = false): DeviceProfile? {
        val name = o.optString("name").trim()
        if (name.isEmpty()) return null
        val id = o.optString("id").ifBlank {
            "user_" + Integer.toHexString((name + System.currentTimeMillis()).hashCode())
        }
        val match = o.optJSONObject("match")
        val prefixes = ArrayList<String>()
        val serviceUuids = ArrayList<UUID>()
        match?.optJSONArray("namePrefixes")?.let { arr ->
            for (i in 0 until arr.length()) arr.optString(i).takeIf { it.isNotBlank() }?.let { prefixes.add(it) }
        }
        match?.optJSONArray("serviceUuids")?.let { arr ->
            for (i in 0 until arr.length()) parseUuid(arr.optString(i))?.let { serviceUuids.add(it) }
        }
        val caps = ArrayList<String>()
        o.optJSONArray("capabilities")?.let { arr ->
            for (i in 0 until arr.length()) arr.optString(i).takeIf { it.isNotBlank() }?.let { caps.add(it) }
        }
        val battery = o.optJSONObject("battery")
        val cameraObj = o.optJSONObject("camera")
        val notes = ArrayList<String>()
        o.optJSONArray("notes")?.let { arr ->
            for (i in 0 until arr.length()) arr.optString(i).takeIf { it.isNotBlank() }?.let { notes.add(it) }
        }
        val candidates = ArrayList<CameraSpec>()
        o.optJSONArray("cameraCandidates")?.let { arr ->
            for (i in 0 until arr.length()) {
                val c = arr.optJSONObject(i) ?: continue
                candidates.add(
                    CameraSpec(
                        mode = c.optString("mode", "ble"),
                        label = c.optString("label", "Проверить камеру"),
                        service = parseUuid(c.optString("service")),
                        triggerChar = parseUuid(c.optString("triggerCharacteristic")),
                        dataChar = parseUuid(c.optString("dataCharacteristic")),
                        trigger = try {
                            if (c.optString("trigger").isBlank()) byteArrayOf(0x01) else parsePayload(c.optString("trigger"))
                        } catch (e: Exception) {
                            byteArrayOf(0x01)
                        },
                        framing = c.optString("framing", "jpeg"),
                        waitMs = c.optInt("waitMs", 1200)
                    )
                )
            }
        }
        val camera = cameraObj?.let {
            CameraSpec(
                mode = it.optString("mode", "demo"),
                label = it.optString("label", "Сделать снимок"),
                service = parseUuid(it.optString("service")),
                triggerChar = parseUuid(it.optString("triggerCharacteristic")),
                dataChar = parseUuid(it.optString("dataCharacteristic")),
                trigger = try {
                    if (it.optString("trigger").isBlank()) byteArrayOf(0x01)
                    else parsePayload(it.optString("trigger"))
                } catch (e: Exception) {
                    byteArrayOf(0x01)
                },
                framing = it.optString("framing", "jpeg"),
                httpUrl = it.optString("httpUrl"),
                wifiSsid = it.optString("wifiSsid"),
                wifiPassword = it.optString("wifiPassword"),
                waitMs = it.optInt("waitMs", 1200),
                demoAsset = it.optString("demoAsset", "demo/glasses_photo.jpg")
            )
        }
        return DeviceProfile(
            id = id,
            name = name,
            vendor = o.optString("vendor"),
            description = o.optString("description"),
            namePrefixes = prefixes,
            serviceUuids = serviceUuids,
            capabilities = if (caps.isEmpty()) listOf("battery", "device_info") else caps,
            batteryService = parseUuid(battery?.optString("service") ?: ""),
            batteryChar = parseUuid(battery?.optString("characteristic") ?: ""),
            camera = camera,
            notes = notes,
            builtIn = builtIn,
            auto = o.optBoolean("auto", false),
            cameraCandidates = candidates
        )
    }
}

/** Хранилище профилей: встроенные (assets) + пользовательские (files). */
class ProfileStore(private val ctx: Context) {

    private val userDir = File(ctx.filesDir, "profiles")
    val all = ArrayList<DeviceProfile>()
    private var loaded = false

    fun load(): List<DeviceProfile> {
        all.clear()
        // Встроенные
        try {
            val names = ctx.assets.list("profiles") ?: emptyArray()
            for (n in names.sorted()) {
                try {
                    val text = ctx.assets.open("profiles/$n").bufferedReader().use { it.readText() }
                    ProfileParser.parse(JSONObject(text), builtIn = true)?.let { all.add(it) }
                } catch (e: Exception) {
                    // один битый профиль не должен ломать остальные
                }
            }
        } catch (ignored: Exception) {
        }
        // Пользовательские
        userDir.mkdirs()
        userDir.listFiles { f -> f.name.endsWith(".json") }?.sortedBy { it.name }?.forEach { f ->
            try {
                val p = ProfileParser.parse(JSONObject(f.readText()), builtIn = false)
                if (p != null) all.add(p)
            } catch (ignored: Exception) {
            }
        }
        loaded = true
        return all
    }

    fun ensureLoaded(): List<DeviceProfile> = if (loaded) all else load()

    fun byId(id: String?): DeviceProfile? =
        if (id == null) null else ensureLoaded().firstOrNull { it.id == id }

    fun bestFor(item: ScanItem): DeviceProfile? {
        val candidates = ensureLoaded().map { it to it.scoreFor(item) }.filter { it.second > 0 }
        return candidates.maxByOrNull { it.second }?.first
    }

    fun matching(item: ScanItem): List<DeviceProfile> =
        ensureLoaded().filter { it.scoreFor(item) > 0 }

    fun saveUser(profile: DeviceProfile) {
        userDir.mkdirs()
        val safeId = profile.id.replace(Regex("[^a-zA-Z0-9_\\-]"), "_")
        val file = File(userDir, "$safeId.json")
        file.writeText(profile.toJson().toString(2))
        loaded = false
        load()
    }

    fun deleteUser(id: String): Boolean {
        val safeId = id.replace(Regex("[^a-zA-Z0-9_\\-]"), "_")
        val file = File(userDir, "$safeId.json")
        val ok = file.delete()
        loaded = false
        load()
        return ok
    }

    fun importJson(text: String): DeviceProfile? {
        return try {
            val p = ProfileParser.parse(JSONObject(text), builtIn = false) ?: return null
            val withId = if (byId(p.id) != null || p.id.startsWith("user_") || p.id.contains("_")) {
                p.copy(id = "user_" + System.currentTimeMillis().toString(16))
            } else p
            saveUser(withId)
            withId
        } catch (e: Exception) {
            null
        }
    }

    fun nextUserId(): String = "user_" + System.currentTimeMillis().toString(16)
}
