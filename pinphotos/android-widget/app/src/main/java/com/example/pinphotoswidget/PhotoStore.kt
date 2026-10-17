package com.example.pinphotoswidget

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import android.util.Base64
import java.security.MessageDigest
import java.io.File
import java.util.UUID

data class Photo(
    val id: String,
    var name: String,
    var albums: MutableList<String> = mutableListOf(),
    var tags: MutableList<String> = mutableListOf(),
    var note: String = "",
    var pinned: Boolean = false,
    val createdAt: Long = System.currentTimeMillis(),
    val file: String,
    val mime: String = "image/jpeg"
) {
    /** Первый альбом для старых мест интерфейса; фото может состоять в нескольких альбомах. */
    val album: String get() = albums.firstOrNull().orEmpty()
    fun fileIn(dir: File) = File(dir, file)
}

data class AlbumSecurity(
    val name: String,
    val pinHash: String = "",
    val salt: String = "",
    val biometric: Boolean = false
) {
    // Закрыть альбом можно только паролем. Отпечаток — способ открытия, но не самостоятельная защита.
    val locked: Boolean get() = pinHash.isNotEmpty()
}

object PhotoStore {
    private const val DIR = "photos"
    private const val META = "meta.json"

    fun dir(context: Context) = File(context.filesDir, DIR).apply { mkdirs() }
    private fun metaFile(context: Context) = File(dir(context), META)

    @Synchronized
    fun list(context: Context): MutableList<Photo> {
        val f = metaFile(context)
        if (!f.exists()) return mutableListOf()
        return try {
            val arr = JSONArray(f.readText())
            val result = mutableListOf<Photo>()
            for (i in 0 until arr.length()) {
                val o = arr.getJSONObject(i)
                val tags = mutableListOf<String>()
                o.optJSONArray("tags")?.let { t -> for (j in 0 until t.length()) tags.add(t.optString(j)) }
                val memberships = mutableListOf<String>()
                o.optJSONArray("albums")?.let { a -> for (j in 0 until a.length()) a.optString(j).takeIf { it.isNotBlank() && it != "Разное" }?.let { memberships.add(it) } }
                if (memberships.isEmpty()) o.optString("album").takeIf { it.isNotBlank() && it != "Разное" }?.let { memberships.add(it) }
                val photo = Photo(
                    id = o.getString("id"), name = o.optString("name", "Фото"),
                    albums = memberships, tags = tags,
                    note = o.optString("note"), pinned = o.optBoolean("pinned"),
                    createdAt = o.optLong("createdAt", System.currentTimeMillis()),
                    file = o.getString("file"), mime = o.optString("mime", "image/jpeg")
                )
                if (photo.fileIn(dir(context)).exists()) result.add(photo)
            }
            result.sortedByDescending { it.createdAt }.toMutableList()
        } catch (e: Exception) { mutableListOf() }
    }

    fun pinned(context: Context) = list(context).filter { it.pinned }

    private fun albumsFile(context: Context) = File(dir(context), "albums.json")

    @Synchronized
    fun albums(context: Context): List<String> {
        // Никаких альбомов по умолчанию: только созданные пользователем.
        val result = linkedSetOf<String>()
        try {
            val f = albumsFile(context)
            if (f.exists()) {
                val arr = JSONArray(f.readText())
                for (i in 0 until arr.length()) arr.optString(i).takeIf { it.isNotBlank() }?.let { result.add(it) }
            }
        } catch (e: Exception) { }
        list(context).flatMap { it.albums }.filter { it.isNotBlank() && it != "Разное" }.forEach { result.add(it) }
        return result.toList()
    }

    @Synchronized
    fun createAlbum(context: Context, name: String): String {
        val clean = name.trim().take(50)
        require(clean.isNotEmpty()) { "Название альбома пустое" }
        val all = albums(context).toMutableList()
        if (all.none { it.equals(clean, ignoreCase = true) }) {
            all.add(clean)
            albumsFile(context).writeText(JSONArray(all).toString())
        }
        return all.first { it.equals(clean, ignoreCase = true) }
    }

    // ---------- Альбомы: пароли, отпечаток, слияние, удаление ----------

    private fun securityFile(context: Context) = File(dir(context), "albums_security.json")

    @Synchronized
    fun albumSecurity(context: Context): List<AlbumSecurity> {
        val byName = linkedMapOf<String, AlbumSecurity>()
        albums(context).forEach { byName[it] = AlbumSecurity(it) }
        try {
            val f = securityFile(context)
            if (f.exists()) {
                val arr = JSONArray(f.readText())
                for (i in 0 until arr.length()) {
                    val o = arr.getJSONObject(i)
                    val name = o.optString("name")
                    if (name.isNotBlank()) byName[name] = AlbumSecurity(
                        name = name,
                        pinHash = o.optString("pinHash"),
                        salt = o.optString("salt"),
                        biometric = o.optBoolean("biometric")
                    )
                }
            }
        } catch (e: Exception) { }
        return byName.values.toList()
    }

    fun securityFor(context: Context, album: String): AlbumSecurity =
        albumSecurity(context).firstOrNull { it.name == album } ?: AlbumSecurity(album)

    fun lockedAlbumNames(context: Context): Set<String> =
        albumSecurity(context).filter { it.locked }.map { it.name }.toSet()

    @Synchronized
    private fun saveSecurity(context: Context, item: AlbumSecurity) {
        val all = albumSecurity(context).toMutableList()
        val idx = all.indexOfFirst { it.name == item.name }
        if (idx >= 0) all[idx] = item else all.add(item)
        val arr = JSONArray()
        all.forEach { s -> arr.put(JSONObject().put("name", s.name).put("pinHash", s.pinHash).put("salt", s.salt).put("biometric", s.biometric)) }
        securityFile(context).writeText(arr.toString())
    }

    private fun hashPin(salt: String, pin: String): String {
        val digest = MessageDigest.getInstance("SHA-256").digest("$salt:$pin".toByteArray(Charsets.UTF_8))
        return Base64.encodeToString(digest, Base64.NO_WRAP)
    }

    @Synchronized
    fun setAlbumPin(context: Context, album: String, pin: String) {
        require(pin.matches(Regex("\\d{4}"))) { "Пароль должен состоять из 4 цифр" }
        val salt = UUID.randomUUID().toString()
        val current = securityFor(context, album)
        saveSecurity(context, current.copy(pinHash = hashPin(salt, pin), salt = salt))
    }

    @Synchronized
    fun clearAlbumPin(context: Context, album: String) {
        val current = securityFor(context, album)
        saveSecurity(context, current.copy(pinHash = "", salt = ""))
    }

    fun verifyAlbumPin(context: Context, album: String, pin: String): Boolean {
        val s = securityFor(context, album)
        return s.pinHash.isNotEmpty() && hashPin(s.salt, pin) == s.pinHash
    }

    @Synchronized
    fun setAlbumBiometric(context: Context, album: String, enabled: Boolean) {
        saveSecurity(context, securityFor(context, album).copy(biometric = enabled))
    }

    @Synchronized
    /** Слияние = фотографии получают членство ещё и в целевом альбоме. Из исходного ничего не удаляется. */
    fun mergeAlbums(context: Context, source: String, destination: String): Int {
        if (source == destination) return 0
        val all = list(context); var added = 0
        all.forEach { p ->
            if (source in p.albums && destination !in p.albums) { p.albums.add(destination); added++ }
        }
        if (added > 0) saveAll(context, all)
        return added
    }

    @Synchronized
    fun deleteAlbumWithPhotos(context: Context, album: String): Int {
        val all = list(context)
        val victims = all.filter { album in it.albums }
        victims.forEach { it.fileIn(dir(context)).delete() }
        saveAll(context, all.filterNot { album in it.albums })
        // Убрать альбом из реестра и его защиту
        try {
            val names = albums(context).filterNot { it == album }
            albumsFile(context).writeText(JSONArray(names).toString())
        } catch (e: Exception) { }
        val remaining = albumSecurity(context).filterNot { it.name == album }
        val arr = JSONArray()
        remaining.forEach { s -> arr.put(JSONObject().put("name", s.name).put("pinHash", s.pinHash).put("salt", s.salt).put("biometric", s.biometric)) }
        securityFile(context).writeText(arr.toString())
        return victims.size
    }

    @Synchronized
    fun saveAll(context: Context, photos: List<Photo>) {
        val arr = JSONArray()
        for (p in photos.sortedBy { it.createdAt }) {
            arr.put(JSONObject()
                .put("id", p.id).put("name", p.name).put("album", p.album).put("albums", JSONArray(p.albums))
                .put("tags", JSONArray(p.tags)).put("note", p.note).put("pinned", p.pinned)
                .put("createdAt", p.createdAt).put("file", p.file).put("mime", p.mime))
        }
        metaFile(context).writeText(arr.toString())
    }

    @Synchronized
    fun update(context: Context, photo: Photo) {
        val all = list(context)
        val idx = all.indexOfFirst { it.id == photo.id }
        if (idx >= 0) { all[idx] = photo; saveAll(context, all) }
    }

    @Synchronized
    fun importBytes(context: Context, bytes: ByteArray, mime: String, name: String): Photo {
        val ext = when (mime) { "image/png" -> "png"; "image/webp" -> "webp"; "image/gif" -> "gif"; else -> "jpg" }
        val id = System.currentTimeMillis().toString(36) + UUID.randomUUID().toString().take(6)
        val fileName = "$id.$ext"
        File(dir(context), fileName).writeBytes(bytes)
        val photo = Photo(id = id, name = name.ifBlank { "Фото" }, file = fileName, mime = mime.ifBlank { "image/jpeg" })
        val all = list(context); all.add(0, photo); saveAll(context, all)
        return photo
    }

    @Synchronized
    fun delete(context: Context, photo: Photo) {
        photo.fileIn(dir(context)).delete()
        saveAll(context, list(context).filterNot { it.id == photo.id })
    }
}
