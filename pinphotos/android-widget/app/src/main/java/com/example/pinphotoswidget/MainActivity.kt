package com.example.pinphotoswidget

import android.app.Activity
import android.appwidget.AppWidgetManager
import android.content.ComponentName
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.OpenableColumns
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.ImageView
import android.widget.PopupMenu
import android.widget.TextView
import android.widget.Toast
import androidx.core.content.FileProvider
import androidx.recyclerview.widget.GridLayoutManager
import androidx.recyclerview.widget.RecyclerView
import org.json.JSONObject
import java.io.File
import java.util.concurrent.Executors

/** Полностью нативное приложение «ЗакрепФото» (без WebView): сетка фото, импорт, виджет, иконки. */
class MainActivity : Activity() {
    private lateinit var grid: RecyclerView
    private lateinit var emptyView: View
    private lateinit var widgetStatus: TextView
    private lateinit var countText: TextView
    private var photos: MutableList<Photo> = mutableListOf()
    private val io = Executors.newFixedThreadPool(3)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        grid = findViewById(R.id.grid)
        emptyView = findViewById(R.id.emptyView)
        widgetStatus = findViewById(R.id.widgetStatus)
        countText = findViewById(R.id.countText)
        grid.layoutManager = GridLayoutManager(this, 3)
        findViewById<Button>(R.id.importBtn).setOnClickListener { pickPhotos() }
        findViewById<Button>(R.id.emptyImportBtn).setOnClickListener { pickPhotos() }
        findViewById<Button>(R.id.addWidgetBtn).setOnClickListener { chooseWidgetSize() }
        findViewById<View>(R.id.menuBtn).setOnClickListener { showMenu(it) }
    }

    override fun onResume() { super.onResume(); refresh() }

    private fun refresh() {
        photos = PhotoStore.list(this)
        val pinnedCount = photos.count { it.pinned }
        countText.text = if (photos.isEmpty()) "" else "${photos.size}"
        widgetStatus.text = when {
            photos.isEmpty() -> "Нет фотографий"
            pinnedCount == 0 -> "Нет закреплённых — откройте фото и нажмите «Закрепить»"
            pinnedCount == 1 -> "В виджете: 1 фото"
            else -> "В виджете: $pinnedCount фото · листаются каждые ~30 мин"
        }
        emptyView.visibility = if (photos.isEmpty()) View.VISIBLE else View.GONE
        grid.visibility = if (photos.isEmpty()) View.GONE else View.VISIBLE
        grid.adapter = PhotoAdapter(photos) { photo ->
            startActivity(Intent(this, PhotoActivity::class.java).putExtra("id", photo.id))
        }
        PinnedPhotoWidgetBase.updateAll(this)
    }

    private fun showMenu(anchor: View) {
        val menu = PopupMenu(this, anchor)
        menu.menu.add(0, 1, 0, "Добавить фото")
        menu.menu.add(0, 2, 0, "Добавить виджет…")
        menu.menu.add(0, 3, 0, "Бэкап: сохранить JSON")
        menu.menu.add(0, 4, 0, "Восстановить из JSON")
        menu.menu.add(0, 5, 0, "Иконка: обычная 📌")
        menu.menu.add(0, 6, 0, "Иконка: огненная 🔥")
        menu.menu.add(0, 7, 0, "Иконка: сонная 😴")
        menu.setOnMenuItemClickListener { item ->
            when (item.itemId) {
                1 -> pickPhotos()
                2 -> chooseWidgetSize()
                3 -> startActivityForResult(Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
                    addCategory(Intent.CATEGORY_OPENABLE); type = "application/json"
                    putExtra(Intent.EXTRA_TITLE, "pinphotos-backup.json")
                }, EXPORT_JSON)
                4 -> startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                    addCategory(Intent.CATEGORY_OPENABLE); type = "*/*"
                }, IMPORT_JSON)
                5 -> IconSwitcher.setIcon(this, IconSwitcher.NORMAL)
                6 -> IconSwitcher.setIcon(this, IconSwitcher.FIRE)
                7 -> IconSwitcher.setIcon(this, IconSwitcher.SLEEPY)
            }
            true
        }
        menu.show()
    }

    private fun pickPhotos() {
        val intent = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
            addCategory(Intent.CATEGORY_OPENABLE); type = "image/*"
            putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        startActivityForResult(intent, PICK_PHOTOS)
    }

    private fun chooseWidgetSize() {
        val labels = arrayOf("2 × 2", "3 × 2", "4 × 2", "4 × 3")
        android.app.AlertDialog.Builder(this)
            .setTitle("Размер виджета")
            .setItems(labels) { _, which -> requestPin(PinnedPhotoWidgetBase.PROVIDERS[which]) }
            .show()
    }

    private fun requestPin(cls: Class<out PinnedPhotoWidgetBase>) {
        val manager = AppWidgetManager.getInstance(this)
        val provider = ComponentName(this, cls)
        val ok = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O &&
            manager.isRequestPinAppWidgetSupported &&
            manager.requestPinAppWidget(provider, null, null)
        if (!ok) toast("Лаунчер не поддерживает добавление из приложения: долгое нажатие по рабочему столу → Виджеты → ЗакрепФото")
    }

    @Deprecated("startActivityForResult — осознанно, без лишних зависимостей")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (resultCode != RESULT_OK || data == null) return
        when (requestCode) {
            PICK_PHOTOS -> io.execute {
                var saved = 0
                val uris = mutableListOf<Uri>()
                data.clipData?.let { clip -> for (i in 0 until clip.itemCount) uris.add(clip.getItemAt(i).uri) }
                if (uris.isEmpty()) data.data?.let { uris.add(it) }
                for (uri in uris) {
                    try {
                        val bytes = contentResolver.openInputStream(uri)?.readBytes() ?: continue
                        if (bytes.isEmpty()) continue
                        PhotoStore.importBytes(this, bytes, contentResolver.getType(uri) ?: "image/jpeg", displayName(uri))
                        saved++
                    } catch (e: Exception) { /* одно битое фото не должно валить остальные */ }
                }
                runOnUiThread { toast("Добавлено: $saved"); refresh() }
            }
            EXPORT_JSON -> io.execute {
                try {
                    val arr = org.json.JSONArray()
                    for (p in photos) {
                        val bytes = p.fileIn(PhotoStore.dir(this)).readBytes()
                        arr.put(JSONObject()
                            .put("name", p.name).put("album", p.album).put("tags", org.json.JSONArray(p.tags))
                            .put("note", p.note).put("pinned", p.pinned).put("createdAt", p.createdAt)
                            .put("mime", p.mime)
                            .put("data", android.util.Base64.encodeToString(bytes, android.util.Base64.NO_WRAP)))
                    }
                    val root = JSONObject().put("app", "pinphotos").put("version", 2).put("photos", arr)
                    data.data?.let { uri -> contentResolver.openOutputStream(uri)?.use { it.write(root.toString().toByteArray()) } }
                    runOnUiThread { toast("Бэкап сохранён") }
                } catch (e: Exception) { runOnUiThread { toast("Ошибка бэкапа: ${e.message}") } }
            }
            IMPORT_JSON -> io.execute {
                try {
                    val text = data.data?.let { uri -> contentResolver.openInputStream(uri)?.readBytes()?.toString(Charsets.UTF_8) } ?: ""
                    val arr = JSONObject(text).getJSONArray("photos"); var added = 0
                    for (i in 0 until arr.length()) {
                        val o = arr.getJSONObject(i)
                        val encoded = if (o.has("data")) o.getString("data")
                            else o.optString("dataUrl").substringAfter(",", "")
                        if (encoded.isEmpty()) continue
                        val p = PhotoStore.importBytes(this, android.util.Base64.decode(encoded, android.util.Base64.DEFAULT),
                            o.optString("mime", "image/jpeg"), o.optString("name", "Фото"))
                        p.album = o.optString("album", "Разное"); p.note = o.optString("note")
                        p.pinned = o.optBoolean("pinned")
                        o.optJSONArray("tags")?.let { t -> for (j in 0 until t.length()) p.tags.add(t.optString(j)) }
                        PhotoStore.update(this, p); added++
                    }
                    runOnUiThread { toast("Восстановлено: $added"); refresh() }
                } catch (e: Exception) { runOnUiThread { toast("Ошибка восстановления: ${e.message}") } }
            }
        }
    }

    private fun displayName(uri: Uri): String {
        var name = "Фото"
        try {
            contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c ->
                if (c.moveToFirst()) name = c.getString(0) ?: name
            }
        } catch (e: Exception) { }
        return name.substringBeforeLast('.').ifBlank { "Фото" }
    }

    private fun toast(text: String) = Toast.makeText(this, text, Toast.LENGTH_LONG).show()

    companion object { const val PICK_PHOTOS = 2001; const val EXPORT_JSON = 2002; const val IMPORT_JSON = 2003 }
}

class PhotoAdapter(
    private val items: List<Photo>,
    private val onClick: (Photo) -> Unit
) : RecyclerView.Adapter<PhotoAdapter.Holder>() {
    private val io = Executors.newFixedThreadPool(3)

    class Holder(view: View) : RecyclerView.ViewHolder(view) {
        val thumb: ImageView = view.findViewById(R.id.thumb)
        val badge: TextView = view.findViewById(R.id.badge)
    }

    override fun onCreateViewHolder(parent: ViewGroup, type: Int): Holder =
        Holder(LayoutInflater.from(parent.context).inflate(R.layout.item_photo, parent, false))

    override fun getItemCount() = items.size

    override fun onBindViewHolder(holder: Holder, position: Int) {
        val photo = items[position]
        holder.badge.visibility = if (photo.pinned) View.VISIBLE else View.GONE
        holder.thumb.setImageResource(R.drawable.widget_placeholder)
        holder.thumb.tag = photo.id
        val path = photo.fileIn(PhotoStore.dir(holder.thumb.context)).absolutePath
        io.execute {
            val bmp = decodeSampled(path, 360)
            holder.thumb.post { if (holder.thumb.tag == photo.id && bmp != null) holder.thumb.setImageBitmap(bmp) }
        }
        holder.itemView.setOnClickListener { onClick(photo) }
    }

    private fun decodeSampled(path: String, target: Int): Bitmap? {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(path, bounds)
        if (bounds.outWidth <= 0) return null
        var sample = 1
        while (bounds.outWidth / sample > target * 2) sample *= 2
        return BitmapFactory.decodeFile(path, BitmapFactory.Options().apply { inSampleSize = sample })
    }
}
