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
        val clean = name.trim().take(40)
        require(clean.isNotEmpty()) { "Название альбома пустое" }
        val all = albums(context).toMutableList()
        if (all.none { it.equals(clean, ignoreCase = true) }) {
            all.add(clean)
            albumsFile(context).writeText(JSONArray(all).toString())
        }
        return all.first { it.equals(clean, ignoreCase = true) }
    }

    /**
     * Ручной порядок обычных альбомов. «Разное» навсегда первое: его нельзя сдвинуть,
     * и никакой другой альбом нельзя поставить перед ним.
     */
    @Synchronized
    fun moveAlbum(context: Context, album: String, delta: Int): Boolean {
        if (album == MISC_ALBUM || delta == 0) return false
        val all = albums(context).toMutableList()
        val index = all.indexOf(album)
        val target = index + delta
        if (index <= 0 || target <= 0 || target !in all.indices) return false
        val moved = all.removeAt(index); all.add(target, moved)
        albumsFile(context).writeText(JSONArray(all).toString())
        return true
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
        val existingKey = current.keyWrap.takeIf { it.isNotEmpty() }?.let { VaultCrypto.unwrapWithMaster(it) }
            ?: current.pinKeyWrap.takeIf { it.isNotEmpty() && current.salt.isNotEmpty() }
                ?.let { VaultCrypto.unwrapWithPin(it, pin, current.salt) }
        val key = existingKey ?: VaultCrypto.newAlbumKey()
        // До записи в диск проверяем обе обёртки и само AES-GCM шифрование. Если устройство
        // не смогло выполнить криптографию, выбрасываем понятную ошибку, а альбом не трогаем.
        val masterWrap = VaultCrypto.wrapWithMaster(key)
        val pinWrap = VaultCrypto.wrapWithPin(key, pin, salt)
        val masterOk = VaultCrypto.unwrapWithMaster(masterWrap)?.contentEquals(key) == true
        val pinOk = VaultCrypto.unwrapWithPin(pinWrap, pin, salt)?.contentEquals(key) == true
        check(masterOk && pinOk && VaultCrypto.selfTest(key)) { "Проверка шифрования на устройстве не пройдена" }
        val updated = current.copy(
            pinHash = hashPin(salt, pin), salt = salt, biometric = true,
            keyWrap = masterWrap, pinKeyWrap = pinWrap
        )
        saveSecurity(context, updated)
        sessionAlbumKeys[album] = key
        // Все копии этого альбома на диске превращаются в AES-GCM шифртекст. Ошибка одного
        // файла не должна ронять приложение: фиксируем её, но остальные фото продолжаем.
        // ВАЖНО: после конвертации сохраняем метаданные. Раньше encrypted=true оставался
        // только у объектов в памяти, а meta.json по-прежнему говорил encrypted=false.
        // Из-за этого после перезапуска видео считалось открытым и плеер/превью пытались
        // читать AES-шифртекст как обычный MP4/JPEG.
        val failures = mutableListOf<String>()
        val allAfterPin = list(context)
        allAfterPin.filter { album in it.albums }.forEach { photo ->
            try {
                if (isLargeOrVideo(context, photo)) rewritePhotoStorage(context, photo)
                else plainBytes(context, photo)?.let { plain -> writeStored(context, photo, plain) }
                    ?: failures.add(photo.name)
            } catch (e: Exception) { failures.add(photo.name) }
        }
        saveAll(context, allAfterPin)
        if (failures.isNotEmpty()) {
            try { java.io.File(dir(context), "security_error.txt").writeText("Не зашифровано: " + failures.joinToString(", ")) } catch (ignored: Exception) { }
        }
    }

    @Synchronized
    fun clearAlbumPin(context: Context, album: String) {
        val affectedBefore = list(context).filter { album in it.albums }
        val affectedIds = affectedBefore.map { it.id }.toSet()
        // До стирания ключей: маленькие фото расшифровываем в память, большие/видео — потоково в кэш-файл.
        val smallPlains = affectedBefore.filterNot { isLargeOrVideo(context, it) }
            .mapNotNull { photo -> plainBytes(context, photo)?.let { photo.id to it } }.toMap()
        affectedBefore.filter { isLargeOrVideo(context, it) }.forEach { playableFile(context, it) }
        val current = securityFor(context, album)
        saveSecurity(context, current.copy(pinHash = "", salt = "", keyWrap = "", pinKeyWrap = ""))
        val all = list(context)
        all.forEach { photo ->
            if (photo.id in affectedIds) {
                if (isLargeOrVideo(context, photo)) rewritePhotoStorage(context, photo)
                else smallPlains[photo.id]?.let { plain ->
                    photo.encrypted = false; photo.fileIn(dir(context)).writeBytes(plain)
                }
            }
        }
        sessionAlbumKeys.remove(album)
        saveAll(context, all)
    }

    fun verifyAlbumPin(context: Context, album: String, pin: String): Boolean {
        val s = securityFor(context, album)
        val ok = s.pinHash.isNotEmpty() && hashPin(s.salt, pin) == s.pinHash
        if (ok) {
            // Сразу восстанавливаем ключ альбома из PIN-wrap и держим только в памяти.
            VaultCrypto.unwrapWithPin(s.pinKeyWrap, pin, s.salt)?.let { sessionAlbumKeys[album] = it }
        }
        return ok
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
            val hash = contentHash(context, photo)
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

    private val durationCache = java.util.concurrent.ConcurrentHashMap<String, String>()

    /** Плашка длительности для главного экрана: видео — METADATA, GIF — сумма задержек кадров. */
    fun mediaDurationLabel(context: Context, photo: Photo): String? {
        val isVideo = photo.mime.startsWith("video/")
        val isGif = photo.mime == "image/gif" || photo.file.endsWith(".gif", ignoreCase = true)
        if (!isVideo && !isGif) return null
        durationCache[photo.id]?.let { return it }
        if (isVideo) {
            val videoLabel = try {
                val playable = playableFile(context, photo)
                if (playable == null) null else {
                    val retriever = android.media.MediaMetadataRetriever()
                    retriever.setDataSource(playable.absolutePath)
                    val ms = retriever.extractMetadata(android.media.MediaMetadataRetriever.METADATA_KEY_DURATION)?.toLongOrNull() ?: 0L
                    retriever.release(); if (ms > 0) "▶ ${formatDuration(ms)}" else "▶ Видео"
                }
            } catch (e: Exception) { "▶ Видео" }
            if (videoLabel != null) durationCache[photo.id] = videoLabel
            return videoLabel
        }
        // GIF сканируем потоково по файлу: не нужно держать весь файл в памяти ради суммы задержек кадров.
        val playable = playableFile(context, photo) ?: return "GIF"
        val ms = try { playable.inputStream().buffered().use { gifDurationMs(it) } } catch (e: Exception) { 0L }
        val label = if (ms > 0) "GIF · ${formatDuration(ms)}" else "GIF"
        durationCache[photo.id] = label
        return label
    }

    private fun gifDurationMs(input: java.io.InputStream): Long {
        var totalHundredths = 0L
        var tail = ByteArray(0)
        val buffer = ByteArray(64 * 1024)
        while (true) {
            val read = input.read(buffer)
            if (read <= 0) break
            val chunk = tail + buffer.copyOf(read)
            var i = 0
            while (i + 7 < chunk.size) {
                if (chunk[i] == 0x21.toByte() && chunk[i + 1] == 0xF9.toByte() && chunk[i + 2] == 4.toByte()) {
                    val delay = (chunk[i + 4].toInt() and 0xFF) or ((chunk[i + 5].toInt() and 0xFF) shl 8)
                    totalHundredths += delay
                    i += 8
                } else i++
            }
            tail = chunk.copyOfRange((chunk.size - 7).coerceAtLeast(0), chunk.size)
        }
        return totalHundredths * 10L
    }

    private fun formatDuration(ms: Long): String {
        val totalSeconds = (ms / 1000L).coerceAtLeast(0L)
        val h = totalSeconds / 3600; val m = (totalSeconds % 3600) / 60; val sec = totalSeconds % 60
        return if (h > 0) "%d:%02d:%02d".format(h, m, sec) else "%d:%02d".format(m, sec)
    }

    fun sha256(bytes: ByteArray): String =
        MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }

    private fun sha256(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buffer = ByteArray(64 * 1024)
            while (true) {
                val read = input.read(buffer)
                if (read <= 0) break
                digest.update(buffer, 0, read)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }

    private fun contentHash(context: Context, photo: Photo): String {
        if (photo.hash.isNotEmpty()) return photo.hash
        playableFile(context, photo)?.let { return sha256(it) }
        return plainBytes(context, photo)?.let { sha256(it) }.orEmpty()
    }

    // Ключи, восстановленные в текущей сессии вводом PIN. Это запасной путь, если
    // Android Keystore потерял/отозвал master-key: PIN-wrap при этом остаётся рабочим.
    private val sessionAlbumKeys = java.util.concurrent.ConcurrentHashMap<String, ByteArray>()

    fun albumKey(context: Context, album: String): ByteArray? {
        sessionAlbumKeys[album]?.let { return it }
        val security = securityFor(context, album)
        val key = security.keyWrap.takeIf { it.isNotEmpty() }?.let { VaultCrypto.unwrapWithMaster(it) }
        if (key != null) sessionAlbumKeys[album] = key
        return key
    }

    /** Потоковый импорт: видео не загружается целиком в оперативную память. */
    @Synchronized
    fun importStream(context: Context, input: java.io.InputStream, mime: String, name: String): Photo {
        val ext = when {
            mime == "image/png" -> "png"; mime == "image/webp" -> "webp"; mime == "image/gif" -> "gif"
            mime.startsWith("video/") -> if (mime.contains("webm")) "webm" else if (mime.contains("quicktime")) "mov" else "mp4"
            else -> "jpg"
        }
        val id = System.currentTimeMillis().toString(36) + UUID.randomUUID().toString().take(6)
        val fileName = "$id.$ext"
        val outFile = File(dir(context), fileName)
        val digest = MessageDigest.getInstance("SHA-256")
        input.use { stream ->
            outFile.outputStream().use { out ->
                val buffer = ByteArray(64 * 1024)
                while (true) {
                    val read = stream.read(buffer)
                    if (read <= 0) break
                    digest.update(buffer, 0, read); out.write(buffer, 0, read)
                }
            }
        }
        val hash = digest.digest().joinToString("") { "%02x".format(it) }
        val photo = Photo(id = id, name = name.trim().take(40).ifBlank { "Фото" }, file = fileName, mime = mime.ifBlank { "image/jpeg" }, hash = hash)
        val all = list(context); all.add(0, photo); saveAll(context, all)
        return photo
    }

    /** Фактическая проверка файла по магической подписи, даже если в старых метаданных encrypted=false. */
    fun storedIsEncrypted(context: Context, photo: Photo): Boolean {
        if (photo.encrypted) return true
        return try {
            val file = photo.fileIn(dir(context))
            if (!file.exists() || file.length() < 6) false else file.inputStream().use { input ->
                val magic = ByteArray(6); var offset = 0
                while (offset < magic.size) { val n = input.read(magic, offset, magic.size - offset); if (n <= 0) break; offset += n }
                offset == magic.size && magic.toString(Charsets.US_ASCII) == "PFENC1"
            }
        } catch (e: Exception) { false }
    }

    /** Файл, который можно отдать плееру/превью. Обычное видео не копируем и не грузим в RAM. */
    fun playableFile(context: Context, photo: Photo): File? {
        val source = photo.fileIn(dir(context))
        if (!source.exists()) return null
        if (!storedIsEncrypted(context, photo)) return source
        val cached = File(context.cacheDir, "decrypted_${photo.id}.${source.extension.ifBlank { "mp4" }}")
        if (cached.exists() && cached.length() > 0) return cached
        return try {
            val key = photo.albums.firstNotNullOfOrNull { albumKey(context, it) } ?: return null
            copyDecryptedTo(source, key, cached); cached
        } catch (e: Exception) { cached.delete(); null }
    }

    /** Потоковое копирование открытых байтов без загрузки всего видео в память. */
    fun copyPlainTo(context: Context, photo: Photo, outFile: File): Boolean {
        val source = photo.fileIn(dir(context))
        if (!source.exists()) return false
        return try {
            if (!photo.encrypted) { source.copyTo(outFile, overwrite = true); true }
            else {
                val key = photo.albums.firstNotNullOfOrNull { albumKey(context, it) } ?: return false
                copyDecryptedTo(source, key, outFile); true
            }
        } catch (e: Exception) { false }
    }

    private fun copyDecryptedTo(source: File, key: ByteArray, outFile: File) {
        source.inputStream().use { raw ->
            val magic = ByteArray(6); raw.read(magic)
            val iv = ByteArray(12); raw.read(iv)
            val cipher = javax.crypto.Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(javax.crypto.Cipher.DECRYPT_MODE, javax.crypto.spec.SecretKeySpec(key, "AES"), javax.crypto.spec.GCMParameterSpec(128, iv))
            javax.crypto.CipherInputStream(raw, cipher).use { decrypted ->
                outFile.outputStream().use { out -> decrypted.copyTo(out, 64 * 1024) }
            }
        }
    }

    private fun copyEncryptedTo(sourcePlain: File, key: ByteArray, outFile: File) {
        val iv = ByteArray(12).also { java.security.SecureRandom().nextBytes(it) }
        val cipher = javax.crypto.Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(javax.crypto.Cipher.ENCRYPT_MODE, javax.crypto.spec.SecretKeySpec(key, "AES"), javax.crypto.spec.GCMParameterSpec(128, iv))
        sourcePlain.inputStream().use { input ->
            outFile.outputStream().use { rawOut ->
                rawOut.write("PFENC1".toByteArray(Charsets.US_ASCII)); rawOut.write(iv)
                javax.crypto.CipherOutputStream(rawOut, cipher).use { encrypted -> input.copyTo(encrypted, 64 * 1024) }
            }
        }
    }

    /** Перезапись хранилища фото потоково: большие файлы и видео не загружаются в RAM целиком. */
    fun rewritePhotoStorage(context: Context, photo: Photo) {
        val target = photo.fileIn(dir(context))
        val lockedAlbum = photo.albums.firstOrNull { securityFor(context, it).locked }
        val shouldEncrypt = lockedAlbum != null && albumKey(context, lockedAlbum) != null
        if (photo.encrypted == shouldEncrypt && target.exists()) return
        val plainSource = playableFile(context, photo) ?: return
        val temp = File(dir(context), photo.file + ".tmp")
        try {
            if (shouldEncrypt) {
                val key = albumKey(context, lockedAlbum!!) ?: return
                copyEncryptedTo(plainSource, key, temp); photo.encrypted = true
            } else {
                plainSource.copyTo(temp, overwrite = true); photo.encrypted = false
            }
            if (target.exists()) target.delete()
            if (!temp.renameTo(target)) { temp.copyTo(target, overwrite = true); temp.delete() }
        } catch (e: Exception) { temp.delete() }
    }

    private fun isLargeOrVideo(context: Context, photo: Photo): Boolean =
        photo.mime.startsWith("video/") || photo.fileIn(dir(context)).length() > 16L * 1024L * 1024L

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

    private fun decodeSampledFile(file: File, target: Int): android.graphics.Bitmap? {
        val bounds = android.graphics.BitmapFactory.Options().apply { inJustDecodeBounds = true }
        android.graphics.BitmapFactory.decodeFile(file.absolutePath, bounds)
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return null
        var sample = 1
        while (bounds.outWidth / sample > target * 2 || bounds.outHeight / sample > target * 2) sample *= 2
        return android.graphics.BitmapFactory.decodeFile(
            file.absolutePath,
            android.graphics.BitmapFactory.Options().apply { inSampleSize = sample }
        )
    }

    /** Уже готовая миниатюра из памяти: без декодирования и без ожидания потока. */
    fun cachedBitmap(photo: Photo, target: Int = 360): android.graphics.Bitmap? {
        val cacheKey = "${photo.id}:$target:${photo.file}"
        return synchronized(bitmapCache) { bitmapCache.get(cacheKey) }
    }

    fun decodeBitmap(context: Context, photo: Photo, target: Int = 900): android.graphics.Bitmap? {
        val cacheKey = "${photo.id}:$target:${photo.file}"
        synchronized(bitmapCache) { bitmapCache.get(cacheKey)?.let { return it } }
        // Видео: статичный кадр-превью. В виджете видео и GIF всегда статичны (RemoteViews не анимирует).
        if (photo.mime.startsWith("video/")) {
            val frame = videoFrame(context, photo, target)
            if (frame != null) synchronized(bitmapCache) { bitmapCache.put(cacheKey, frame) }
            return frame
        }
        // Зашифрованные изображения: сначала потоково расшифровываем во временный файл,
        // затем сэмплированно декодируем его. Нельзя читать весь шифртекст в ByteArray:
        // на больших фото это и была дорога к нехватке памяти при открытии закрытого альбома.
        if (storedIsEncrypted(context, photo)) {
            val plainFile = playableFile(context, photo) ?: return null
            val decodedEncrypted = decodeSampledFile(plainFile, target)
            if (decodedEncrypted != null) {
                synchronized(bitmapCache) { bitmapCache.put(cacheKey, decodedEncrypted) }
                return decodedEncrypted
            }
            return null
        }
        // Открытые изображения декодируем сэмплированно прямо из файла, не создавая ByteArray всего файла.
        if (!photo.encrypted) {
            val decoded = decodeSampledFile(photo.fileIn(dir(context)), target)
            if (decoded != null) {
                synchronized(bitmapCache) { bitmapCache.put(cacheKey, decoded) }
                return decoded
            }
        }
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

    fun videoFrame(context: Context, photo: Photo, target: Int = 1100): android.graphics.Bitmap? {
        return try {
            val playable = playableFile(context, photo) ?: return null
            val retriever = android.media.MediaMetadataRetriever()
            retriever.setDataSource(playable.absolutePath)
            val frame = retriever.getFrameAtTime(0)
            retriever.release()
            if (frame == null || target <= 0) frame
            else {
                val largest = maxOf(frame.width, frame.height)
                if (largest <= target) frame else {
                    val scale = target.toFloat() / largest.toFloat()
                    val scaled = android.graphics.Bitmap.createScaledBitmap(
                        frame,
                        (frame.width * scale).toInt().coerceAtLeast(1),
                        (frame.height * scale).toInt().coerceAtLeast(1),
                        true
                    )
                    if (scaled !== frame) frame.recycle()
                    scaled
                }
            }
        } catch (e: Exception) { null }
    }

    /** Создаёт действительно независимую копию: новый id и отдельный файл. Удаление одной не трогает другую. */
    @Synchronized
    fun duplicatePhoto(context: Context, source: Photo, destinationAlbum: String? = null, widgetId: Int = 0): Photo? {
        val ext = source.file.substringAfterLast('.', "jpg")
        val id = System.currentTimeMillis().toString(36) + UUID.randomUUID().toString().take(6)
        val copy = Photo(
            id = id, name = source.name.trim().take(40).ifBlank { "Фото" },
            albums = destinationAlbum?.let { mutableListOf(it) } ?: mutableListOf(),
            tags = source.tags.toMutableList(), note = source.note,
            pinned = false, widgetId = widgetId,
            createdAt = System.currentTimeMillis(), file = "$id.$ext", mime = source.mime
        )
        if (isLargeOrVideo(context, source)) {
            // Независимая копия большого файла создаётся потоково, без ByteArray всего видео/фото.
            val plain = playableFile(context, source) ?: return null
            copy.hash = source.hash.ifEmpty { sha256(plain) }
            val target = copy.fileIn(dir(context))
            val lockedAlbum = copy.albums.firstOrNull { securityFor(context, it).locked }
            val key = lockedAlbum?.let { albumKey(context, it) }
            if (lockedAlbum != null && key != null) {
                copyEncryptedTo(plain, key, target); copy.encrypted = true
            } else {
                plain.copyTo(target, overwrite = true); copy.encrypted = false
            }
        } else {
            val plain = plainBytes(context, source) ?: return null
            copy.hash = sha256(plain)
            writeStored(context, copy, plain)
        }
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
        val clean = newNameRaw.trim().take(40)
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
        photo.name = photo.name.trim().take(40).ifBlank { "Фото" }
        val all = list(context)
        val idx = all.indexOfFirst { it.id == photo.id }
        if (idx >= 0) {
            if (isLargeOrVideo(context, all[idx])) {
                // Критично для видео: нельзя читать весь файл в ByteArray ради смены альбома.
                photo.encrypted = all[idx].encrypted
                if (photo.hash.isEmpty()) photo.hash = all[idx].hash
                rewritePhotoStorage(context, photo)
            } else {
                plainBytes(context, all[idx])?.let { plain -> writeStored(context, photo, plain) }
            }
            all[idx] = photo; saveAll(context, all)
        }
    }

    @Synchronized
    fun delete(context: Context, photo: Photo) {
        photo.fileIn(dir(context)).delete()
        saveAll(context, list(context).filterNot { it.id == photo.id })
    }
}
