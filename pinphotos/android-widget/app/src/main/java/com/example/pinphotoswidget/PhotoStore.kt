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
    /** Отдельный «альбом виджета»: >0 только у независимых копий для конкретного виджета. */
    var widgetId: Int = 0,
    /** SHA-256 открытых байтов: поиск дубликатов внутри одной коллекции. */
    var hash: String = "",
    var encrypted: Boolean = false,
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
    val biometric: Boolean = false,
    /** DEK альбома, завёрнутый ключом Android Keystore / ключом из PIN. Открытого ключа на диске нет. */
    val keyWrap: String = "",
    val pinKeyWrap: String = ""
) {
    // Закрыть альбом можно только паролем. Отпечаток — способ открытия, но не самостоятельная защита.
    val locked: Boolean get() = pinHash.isNotEmpty()
}

object PhotoStore {
    const val MISC_ALBUM = "Разное"
    // Небольшой общий кэш превью: без него каждый refresh заново декодировал все миниатюры и мог перегружать память.
    private val bitmapCache = object : android.util.LruCache<String, android.graphics.Bitmap>(18 * 1024) {
        override fun sizeOf(key: String, value: android.graphics.Bitmap): Int = (value.byteCount / 1024).coerceAtLeast(1)
    }
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
                o.optJSONArray("albums")?.let { a -> for (j in 0 until a.length()) a.optString(j).takeIf { it.isNotBlank() }?.let { memberships.add(it) } }
                if (memberships.isEmpty()) o.optString("album").takeIf { it.isNotBlank() }?.let { memberships.add(it) }
                // «Разное» — предустановленный домашний альбом. Старые фото «без альбома» переезжают в него.
                if (memberships.isEmpty() && o.optInt("widgetId", 0) == 0) memberships.add(MISC_ALBUM)
                val photo = Photo(
                    id = o.getString("id"), name = o.optString("name", "Фото"),
                    albums = memberships, tags = tags,
                    note = o.optString("note"), pinned = o.optBoolean("pinned"),
                    widgetId = o.optInt("widgetId", 0), hash = o.optString("hash"),
                    encrypted = o.optBoolean("encrypted"),
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
        // Единственный предустановленный альбом — «Разное». Остальные создаёт пользователь.
        val result = linkedSetOf<String>(MISC_ALBUM)
        try {
            val f = albumsFile(context)
            if (f.exists()) {
                val arr = JSONArray(f.readText())
                for (i in 0 until arr.length()) arr.optString(i).takeIf { it.isNotBlank() }?.let { result.add(it) }
            }
        } catch (e: Exception) { }
        list(context).flatMap { it.albums }.filter { it.isNotBlank() }.forEach { result.add(it) }
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
                        biometric = o.optBoolean("biometric"), keyWrap = o.optString("keyWrap"), pinKeyWrap = o.optString("pinKeyWrap")
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
        all.forEach { s -> arr.put(JSONObject().put("name", s.name).put("pinHash", s.pinHash).put("salt", s.salt).put("biometric", s.biometric).put("keyWrap", s.keyWrap).put("pinKeyWrap", s.pinKeyWrap)) }
        securityFile(context).writeText(arr.toString())
    }

    private fun hashPin(salt: String, pin: String): String {
        val digest = MessageDigest.getInstance("SHA-256").digest("$salt:$pin".toByteArray(Charsets.UTF_8))
        return Base64.encodeToString(digest, Base64.NO_WRAP)
    }

    @Synchronized
    fun setAlbumPin(context: Context, album: String, pin: String) {
        require(pin.matches(Regex("\\d{4}"))) { "Пароль должен состоять из 4 цифр" }
        val current = securityFor(context, album)
        val saltBytes = ByteArray(16).also { java.security.SecureRandom().nextBytes(it) }
        val salt = Base64.encodeToString(saltBytes, Base64.NO_WRAP)
        val key = current.keyWrap.takeIf { it.isNotEmpty() }?.let { VaultCrypto.unwrapWithMaster(it) } ?: VaultCrypto.newAlbumKey()
        val updated = current.copy(
            pinHash = hashPin(salt, pin), salt = salt,
            keyWrap = VaultCrypto.wrapWithMaster(key),
            pinKeyWrap = VaultCrypto.wrapWithPin(key, pin, salt)
        )
        saveSecurity(context, updated)
        // Все копии этого альбома на диске превращаются в AES-GCM шифртекст.
        list(context).filter { album in it.albums }.forEach { photo ->
            val plain = plainBytes(context, photo)
            if (plain != null) writeStored(context, photo, plain)
        }
    }

    @Synchronized
    fun clearAlbumPin(context: Context, album: String) {
        val affected = list(context).filter { album in it.albums }
        val plains = affected.mapNotNull { photo -> plainBytes(context, photo)?.let { photo.id to it } }.toMap()
        val current = securityFor(context, album)
        saveSecurity(context, current.copy(pinHash = "", salt = "", keyWrap = "", pinKeyWrap = ""))
        affected.forEach { photo ->
            plains[photo.id]?.let { plain ->
                photo.encrypted = false
                photo.fileIn(dir(context)).writeBytes(plain)
            }
        }
        // saveAll ниже в update не нужен: encrypted-флаг пересохранит ближайшая операция,
        // но сохраняем сразу корректный флаг.
        val all = list(context)
        all.forEach { if (it.id in plains.keys) it.encrypted = false }
        saveAll(context, all)
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
    /** Слияние создаёт НЕЗАВИСИМЫЕ копии в целевом альбоме. В исходном ничего не удаляется,
     *  а удаление копии в одном альбоме не трогает копию в другом. Дубликат внутри целевого не создаём. */
    fun mergeAlbums(context: Context, source: String, destination: String): Int {
        if (source == destination) return 0
        var added = 0
        val sources = list(context).filter { source in it.albums && it.widgetId == 0 }
        for (photo in sources) {
            val hash = plainBytes(context, photo)?.let { sha256(it) } ?: photo.hash
            if (findDuplicate(context, hash, destination) == null) {
                if (duplicatePhoto(context, photo, destinationAlbum = destination) != null) added++
            }
        }
        return added
    }

    @Synchronized
    fun deleteAlbumWithPhotos(context: Context, album: String): Int {
        if (album == MISC_ALBUM) return 0 // «Разное» удалить нельзя
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
        remaining.forEach { s -> arr.put(JSONObject().put("name", s.name).put("pinHash", s.pinHash).put("salt", s.salt).put("biometric", s.biometric).put("keyWrap", s.keyWrap).put("pinKeyWrap", s.pinKeyWrap)) }
        securityFile(context).writeText(arr.toString())
        return victims.size
    }

    fun sha256(bytes: ByteArray): String =
        MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }

    fun albumKey(context: Context, album: String): ByteArray? {
        val security = securityFor(context, album)
        return security.keyWrap.takeIf { it.isNotEmpty() }?.let { VaultCrypto.unwrapWithMaster(it) }
    }

    /** Открытые байты фото. Для закрытых альбомов расшифровывает AES-GCM в память, файл не трогает. */
    fun plainBytes(context: Context, photo: Photo): ByteArray? {
        val file = photo.fileIn(dir(context))
        if (!file.exists()) return null
        val stored = file.readBytes()
        if (!photo.encrypted && !VaultCrypto.isEncrypted(stored)) {
            if (photo.hash.isEmpty()) photo.hash = sha256(stored)
            return stored
        }
        for (album in photo.albums) {
            val key = albumKey(context, album) ?: continue
            VaultCrypto.decrypt(key, stored)?.let { plain ->
                if (photo.hash.isEmpty()) photo.hash = sha256(plain)
                return plain
            }
        }
        return null
    }

    fun writeStored(context: Context, photo: Photo, plain: ByteArray) {
        photo.hash = sha256(plain)
        val lockedAlbum = photo.albums.firstOrNull { securityFor(context, it).locked }
        val key = lockedAlbum?.let { albumKey(context, it) }
        if (lockedAlbum != null && key != null) {
            photo.fileIn(dir(context)).writeBytes(VaultCrypto.encrypt(key, plain))
            photo.encrypted = true
        } else {
            photo.fileIn(dir(context)).writeBytes(plain)
            photo.encrypted = false
        }
    }

    fun decodeBitmap(context: Context, photo: Photo, target: Int = 900): android.graphics.Bitmap? {
        // Видео: статичный кадр-превью. В виджете видео и GIF всегда статичны (RemoteViews не анимирует).
        if (photo.mime.startsWith("video/")) return videoFrame(context, photo)
        val cacheKey = "${photo.id}:$target:${photo.file}"
        synchronized(bitmapCache) { bitmapCache.get(cacheKey)?.let { return it } }
        val plain = plainBytes(context, photo) ?: return null
        val bounds = android.graphics.BitmapFactory.Options().apply { inJustDecodeBounds = true }
        android.graphics.BitmapFactory.decodeByteArray(plain, 0, plain.size, bounds)
        if (bounds.outWidth <= 0) return null
        var sample = 1
        while (bounds.outWidth / sample > target * 2 || bounds.outHeight / sample > target * 2) sample *= 2
        val decoded = android.graphics.BitmapFactory.decodeByteArray(plain, 0, plain.size,
            android.graphics.BitmapFactory.Options().apply { inSampleSize = sample })
        if (decoded != null) synchronized(bitmapCache) { bitmapCache.put(cacheKey, decoded) }
        return decoded
    }

    fun videoFrame(context: Context, photo: Photo): android.graphics.Bitmap? {
        return try {
            val plain = plainBytes(context, photo) ?: return null
            val temp = File(context.cacheDir, "preview_${photo.id}.mp4")
            temp.writeBytes(plain)
            val retriever = android.media.MediaMetadataRetriever()
            retriever.setDataSource(temp.absolutePath)
            val frame = retriever.getFrameAtTime(0)
            retriever.release(); temp.delete(); frame
        } catch (e: Exception) { null }
    }

    /** Создаёт действительно независимую копию: новый id и отдельный файл. Удаление одной не трогает другую. */
    @Synchronized
    fun duplicatePhoto(context: Context, source: Photo, destinationAlbum: String? = null, widgetId: Int = 0): Photo? {
        val plain = plainBytes(context, source) ?: return null
        val ext = source.file.substringAfterLast('.', "jpg")
        val id = System.currentTimeMillis().toString(36) + UUID.randomUUID().toString().take(6)
        val copy = Photo(
            id = id, name = source.name,
            albums = destinationAlbum?.let { mutableListOf(it) } ?: mutableListOf(),
            tags = source.tags.toMutableList(), note = source.note,
            pinned = false, widgetId = widgetId, hash = sha256(plain),
            createdAt = System.currentTimeMillis(), file = "$id.$ext", mime = source.mime
        )
        writeStored(context, copy, plain)
        val all = list(context); all.add(0, copy); saveAll(context, all)
        return copy
    }

    /** Внутри одной коллекции дубликат по содержимому не должен существовать второй записью. */
    fun findDuplicate(context: Context, hash: String, album: String?, widgetId: Int = 0): Photo? {
        if (hash.isEmpty()) return null
        return list(context).firstOrNull { photo ->
            photo.hash == hash && photo.widgetId == widgetId &&
                (if (album == null) photo.albums.isEmpty() else album in photo.albums)
        }
    }

    /** Для показа: внутри текущей выборки одинаковое содержимое показываем только первым. */
    fun dedupeForDisplay(photos: List<Photo>): List<Photo> {
        val seen = mutableSetOf<String>(); val result = mutableListOf<Photo>()
        photos.forEach { photo ->
            val key = photo.hash.ifEmpty { photo.id }
            if (seen.add(key)) result.add(photo)
        }
        return result
    }

    /** Переименование обычного альбома: реестр, членство фото и защита переезжают на новое имя. */
    @Synchronized
    fun renameAlbum(context: Context, oldName: String, newNameRaw: String): String {
        require(oldName != MISC_ALBUM) { "Альбом «Разное» переименовать нельзя" }
        val clean = newNameRaw.trim().take(50)
        require(clean.isNotEmpty()) { "Название альбома пустое" }
        require(clean != MISC_ALBUM) { "Название «Разное» занято системным альбомом" }
        val existing = albums(context)
        require(existing.none { it.equals(clean, ignoreCase = true) && !it.equals(oldName, ignoreCase = true) }) {
            "Альбом с таким названием уже есть"
        }
        val canonical = existing.firstOrNull { it.equals(oldName, ignoreCase = true) } ?: oldName
        // Реестр альбомов
        try {
            val renamed = existing.map { if (it == canonical) clean else it }
            albumsFile(context).writeText(JSONArray(renamed).toString())
        } catch (e: Exception) { }
        // Членство фотографий
        val all = list(context); var changed = false
        all.forEach { photo ->
            val idx = photo.albums.indexOf(canonical)
            if (idx >= 0) { photo.albums[idx] = clean; changed = true }
        }
        if (changed) saveAll(context, all)
        // Защита (PIN/ключи шифрования) переезжает следом
        val security = albumSecurity(context)
        if (security.any { it.name == canonical }) {
            val arr = JSONArray()
            security.forEach { item ->
                val moved = if (item.name == canonical) item.copy(name = clean) else item
                arr.put(JSONObject().put("name", moved.name).put("pinHash", moved.pinHash).put("salt", moved.salt)
                    .put("biometric", moved.biometric).put("keyWrap", moved.keyWrap).put("pinKeyWrap", moved.pinKeyWrap))
            }
            securityFile(context).writeText(arr.toString())
        }
        return clean
    }

    @Synchronized
    fun saveAll(context: Context, photos: List<Photo>) {
        val arr = JSONArray()
        for (p in photos.sortedBy { it.createdAt }) {
            arr.put(JSONObject()
                .put("id", p.id).put("name", p.name).put("album", p.album).put("albums", JSONArray(p.albums))
                .put("tags", JSONArray(p.tags)).put("note", p.note).put("pinned", p.pinned)
                .put("widgetId", p.widgetId).put("hash", p.hash).put("encrypted", p.encrypted)
                .put("createdAt", p.createdAt).put("file", p.file).put("mime", p.mime))
        }
        metaFile(context).writeText(arr.toString())
    }

    @Synchronized
    fun update(context: Context, photo: Photo) {
        val all = list(context)
        val idx = all.indexOfFirst { it.id == photo.id }
        if (idx >= 0) {
            plainBytes(context, all[idx])?.let { plain -> writeStored(context, photo, plain) }
            all[idx] = photo; saveAll(context, all)
        }
    }

    @Synchronized
    fun importBytes(context: Context, bytes: ByteArray, mime: String, name: String): Photo {
        val ext = when {
            mime == "image/png" -> "png"; mime == "image/webp" -> "webp"; mime == "image/gif" -> "gif"
            mime.startsWith("video/") -> if (mime.contains("webm")) "webm" else "mp4"
            else -> "jpg"
        }
        val id = System.currentTimeMillis().toString(36) + UUID.randomUUID().toString().take(6)
        val fileName = "$id.$ext"
        File(dir(context), fileName).writeBytes(bytes)
        val photo = Photo(id = id, name = name.ifBlank { "Фото" }, file = fileName, mime = mime.ifBlank { "image/jpeg" }, hash = sha256(bytes))
        val all = list(context); all.add(0, photo); saveAll(context, all)
        return photo
    }

    @Synchronized
    fun delete(context: Context, photo: Photo) {
        photo.fileIn(dir(context)).delete()
        saveAll(context, list(context).filterNot { it.id == photo.id })
    }
}
