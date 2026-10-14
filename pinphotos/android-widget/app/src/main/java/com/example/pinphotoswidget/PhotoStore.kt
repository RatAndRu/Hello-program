package com.example.pinphotoswidget

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.UUID

data class Photo(
    val id: String,
    var name: String,
    var album: String = "Разное",
    var tags: MutableList<String> = mutableListOf(),
    var note: String = "",
    var pinned: Boolean = false,
    val createdAt: Long = System.currentTimeMillis(),
    val file: String,
    val mime: String = "image/jpeg"
) {
    fun fileIn(dir: File) = File(dir, file)
}

/** Нативное хранилище: files/photos/<файл> + meta.json. Совместимо с данными гибридной версии. */
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
                val photo = Photo(
                    id = o.getString("id"), name = o.optString("name", "Фото"),
                    album = o.optString("album", "Разное"), tags = tags,
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

    @Synchronized
    fun saveAll(context: Context, photos: List<Photo>) {
        val arr = JSONArray()
        for (p in photos.sortedBy { it.createdAt }) {
            arr.put(JSONObject()
                .put("id", p.id).put("name", p.name).put("album", p.album)
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
