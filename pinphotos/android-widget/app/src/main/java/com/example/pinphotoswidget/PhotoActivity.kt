package com.example.pinphotoswidget

import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.graphics.BitmapFactory
import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.net.Uri
import android.widget.ArrayAdapter
import android.widget.Spinner
import androidx.core.content.FileProvider
import java.io.File

class PhotoActivity : Activity() {
    private var photo: Photo? = null
    private var ids: List<String> = emptyList()
    private var index: Int = 0

    override fun onCreate(savedInstanceState: Bundle?) {
        UiTheme.apply(this)
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_photo)
        ids = intent.getStringArrayListExtra("ids") ?: arrayListOf()
        if (ids.isEmpty()) intent.getStringExtra("id")?.let { ids = listOf(it) }
        if (ids.isEmpty()) return finish()
        index = intent.getIntExtra("index", 0).coerceIn(0, ids.lastIndex)
        loadCurrent()

        val zoom = findViewById<ZoomImageView>(R.id.fullImage)
        zoom.onHorizontalSwipe = { delta -> move(delta) }
        findViewById<TextView>(R.id.prevBtn).setOnClickListener { move(-1) }
        findViewById<TextView>(R.id.nextBtn).setOnClickListener { move(1) }

        findViewById<Button>(R.id.pinBtn).setOnClickListener {
            val current = photo ?: return@setOnClickListener
            current.pinned = !current.pinned; PhotoStore.update(this, current); renderText()
            PinnedPhotoWidgetBase.updateAll(this)
            Toast.makeText(this, if (current.pinned) "Закреплено — фото в виджете" else "Откреплено", Toast.LENGTH_SHORT).show()
        }
        findViewById<Button>(R.id.shareBtn).setOnClickListener { photo?.let { share(it) } }
        findViewById<Button>(R.id.copyBtn).setOnClickListener { photo?.let { copy(it) } }
        findViewById<Button>(R.id.editBtn).setOnClickListener { photo?.let { edit(it) } }
        findViewById<Button>(R.id.deleteBtn).setOnClickListener {
            val current = photo ?: return@setOnClickListener
            AlertDialog.Builder(this).setTitle("Удалить фото?")
                .setMessage("Копия в приложении будет удалена. Оригинал в галерее не тронем.")
                .setPositiveButton("Удалить") { _, _ ->
                    PhotoStore.delete(this, current); PinnedPhotoWidgetBase.updateAll(this)
                    val remaining = ids.toMutableList().apply { remove(current.id) }
                    if (remaining.isEmpty()) finish() else {
                        ids = remaining; index = index.coerceAtMost(ids.lastIndex); loadCurrent()
                    }
                }
                .setNegativeButton("Отмена", null).show()
        }
    }

    private fun loadCurrent() {
        val all = PhotoStore.list(this)
        photo = all.firstOrNull { it.id == ids[index] }
        val current = photo ?: return
        val opts = BitmapFactory.Options().apply { inSampleSize = 2 }
        findViewById<ImageView>(R.id.fullImage).setImageBitmap(
            BitmapFactory.decodeFile(current.fileIn(PhotoStore.dir(this)).absolutePath, opts)
        )
        findViewById<TextView>(R.id.positionText).text = "${index + 1} / ${ids.size}"
        renderText()
    }

    private fun move(delta: Int) {
        if (ids.size <= 1) return
        index = ((index + delta) % ids.size + ids.size) % ids.size
        loadCurrent()
    }

    private fun renderText() {
        val p = photo ?: return
        findViewById<TextView>(R.id.photoName).text = p.name
        val meta = listOf(p.album, p.tags.joinToString(" ") { "#$it" }, p.note).filter { it.isNotBlank() }.joinToString(" · ")
        findViewById<TextView>(R.id.photoMeta).text = meta
        findViewById<Button>(R.id.pinBtn).text = if (p.pinned) "📌 В виджете" else "Закрепить"
    }

    private fun sharedUri(p: Photo): Uri {
        val src = p.fileIn(PhotoStore.dir(this))
        val dir = File(cacheDir, "shared").apply { mkdirs() }
        val ext = src.extension.ifBlank { "jpg" }
        val out = File(dir, "${p.name.replace(Regex("[^A-Za-z0-9А-Яа-яЁё _-]"), "_")}.$ext")
        src.copyTo(out, overwrite = true)
        return FileProvider.getUriForFile(this, packageName + ".fileprovider", out)
    }

    private fun copy(p: Photo) {
        try {
            val uri = sharedUri(p)
            val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
            clipboard.setPrimaryClip(ClipData.newUri(contentResolver, p.name, uri))
            grantUriPermission(packageName, uri, Intent.FLAG_GRANT_READ_URI_PERMISSION)
            Toast.makeText(this, "Изображение скопировано", Toast.LENGTH_SHORT).show()
        } catch (e: Exception) {
            Toast.makeText(this, "Не удалось скопировать: ${e.message}", Toast.LENGTH_LONG).show()
        }
    }

    private fun share(p: Photo) {
        try {
            val uri = sharedUri(p)
            startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).apply {
                type = p.mime; putExtra(Intent.EXTRA_STREAM, uri)
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            }, "Поделиться"))
        } catch (e: Exception) {
            Toast.makeText(this, "Не удалось поделиться: ${e.message}", Toast.LENGTH_LONG).show()
        }
    }

    private fun edit(p: Photo) {
        val box = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(52, 28, 52, 10) }
        fun styledEdit(value: String, hintText: String) = EditText(this).apply {
            setText(value); hint = hintText; setSingleLine(true)
            setBackgroundResource(R.drawable.input_bg); setTextColor(UiTheme.color(this@PhotoActivity, R.attr.appText)); setHintTextColor(UiTheme.color(this@PhotoActivity, R.attr.appMuted))
        }
        val name = styledEdit(p.name, "Название")
        val albumNames = PhotoStore.albums(this).toMutableList()
        val displayAlbums = mutableListOf("Без альбома").apply { addAll(albumNames) }
        val albumAdapter = object : ArrayAdapter<String>(this@PhotoActivity, R.layout.spinner_item, displayAlbums) {
            override fun getDropDownView(position: Int, convertView: android.view.View?, parent: android.view.ViewGroup): android.view.View {
                val view = super.getDropDownView(position, convertView, parent) as TextView
                view.setBackgroundColor(UiTheme.color(this@PhotoActivity, R.attr.appSurface))
                view.setTextColor(UiTheme.color(this@PhotoActivity, R.attr.appText))
                return view
            }
        }.also { it.setDropDownViewResource(R.layout.spinner_dropdown_item) }
        val album = Spinner(this).apply {
            adapter = albumAdapter
            setSelection(if (p.album.isBlank()) 0 else displayAlbums.indexOf(p.album).coerceAtLeast(0))
            setBackgroundResource(R.drawable.input_bg)
            setPopupBackgroundResource(if (UiTheme.isDark(this@PhotoActivity)) R.drawable.dialog_bg_dark else R.drawable.dialog_bg_light)
        }
        val newAlbum = Button(this).apply {
            text = "＋ Новый альбом"; setTextColor(UiTheme.color(this@PhotoActivity, R.attr.appAccent)); setBackgroundResource(R.drawable.btn_soft)
            setOnClickListener {
                val input = styledEdit("", "Название альбома")
                AlertDialog.Builder(this@PhotoActivity).setTitle("Новый альбом")
                    .setView(LinearLayout(this@PhotoActivity).apply { setPadding(52, 20, 52, 8); addView(input) })
                    .setPositiveButton("Создать") { _, _ ->
                        try {
                            val created = PhotoStore.createAlbum(this@PhotoActivity, input.text.toString())
                            displayAlbums.clear(); displayAlbums.add("Без альбома"); displayAlbums.addAll(PhotoStore.albums(this@PhotoActivity))
                            albumAdapter.notifyDataSetChanged()
                            album.setSelection(displayAlbums.indexOf(created))
                        } catch (e: Exception) { Toast.makeText(this@PhotoActivity, "Введите название", Toast.LENGTH_SHORT).show() }
                    }
                    .setNegativeButton("Отмена", null).show()
            }
        }
        val tags = styledEdit(p.tags.joinToString(", "), "Теги через запятую")
        val note = styledEdit(p.note, "Заметка")
        val lp = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply { topMargin = 10 }
            box.addView(name); box.addView(album, lp); box.addView(newAlbum, lp); box.addView(tags, lp); box.addView(note, lp)
        AlertDialog.Builder(this).setTitle("Изменить фото").setView(box)
            .setPositiveButton("Сохранить") { _, _ ->
                p.name = name.text.toString().ifBlank { p.name }
                p.album = album.selectedItem?.toString().orEmpty().takeUnless { it == "Без альбома" } ?: ""
                p.tags = tags.text.toString().split(",").map { it.trim().trimStart('#') }.filter { it.isNotEmpty() }.toMutableList()
                p.note = note.text.toString()
                PhotoStore.update(this, p); renderText()
            }
            .setNegativeButton("Отмена", null).show()
    }
}
