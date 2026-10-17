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

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_photo)
        val id = intent.getStringExtra("id") ?: return finish()
        photo = PhotoStore.list(this).firstOrNull { it.id == id } ?: return finish()
        val p = photo!!

        val opts = BitmapFactory.Options().apply { inSampleSize = 2 }
        findViewById<ImageView>(R.id.fullImage).setImageBitmap(
            BitmapFactory.decodeFile(p.fileIn(PhotoStore.dir(this)).absolutePath, opts)
        )
        renderText()

        findViewById<Button>(R.id.pinBtn).setOnClickListener {
            p.pinned = !p.pinned; PhotoStore.update(this, p); renderText()
            PinnedPhotoWidgetBase.updateAll(this)
            Toast.makeText(this, if (p.pinned) "Закреплено — фото в виджете" else "Откреплено", Toast.LENGTH_SHORT).show()
        }
        findViewById<Button>(R.id.shareBtn).setOnClickListener { share(p) }
        findViewById<Button>(R.id.copyBtn).setOnClickListener { copy(p) }
        findViewById<Button>(R.id.editBtn).setOnClickListener { edit(p) }
        findViewById<Button>(R.id.deleteBtn).setOnClickListener {
            AlertDialog.Builder(this).setTitle("Удалить фото?")
                .setMessage("Копия в приложении будет удалена. Оригинал в галерее не тронем.")
                .setPositiveButton("Удалить") { _, _ ->
                    PhotoStore.delete(this, p); PinnedPhotoWidgetBase.updateAll(this); finish()
                }
                .setNegativeButton("Отмена", null).show()
        }
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
            setBackgroundResource(R.drawable.input_bg); setTextColor(0xFF24313A.toInt()); setHintTextColor(0xFF98A2AE.toInt())
        }
        val name = styledEdit(p.name, "Название")
        val albums = PhotoStore.albums(this).toMutableList()
        val album = Spinner(this).apply {
            adapter = ArrayAdapter(this@PhotoActivity, android.R.layout.simple_spinner_dropdown_item, albums)
            setSelection(albums.indexOf(p.album).coerceAtLeast(0))
            setBackgroundResource(R.drawable.input_bg)
        }
        val newAlbum = Button(this).apply {
            text = "＋ Новый альбом"; setTextColor(0xFFB45309.toInt()); setBackgroundResource(R.drawable.btn_soft)
            setOnClickListener {
                val input = styledEdit("", "Название альбома")
                AlertDialog.Builder(this@PhotoActivity).setTitle("Новый альбом")
                    .setView(LinearLayout(this@PhotoActivity).apply { setPadding(52, 20, 52, 8); addView(input) })
                    .setPositiveButton("Создать") { _, _ ->
                        try {
                            val created = PhotoStore.createAlbum(this@PhotoActivity, input.text.toString())
                            albums.clear(); albums.addAll(PhotoStore.albums(this@PhotoActivity))
                            (album.adapter as ArrayAdapter<*>).notifyDataSetChanged()
                            album.setSelection(albums.indexOf(created))
                        } catch (e: Exception) { Toast.makeText(this@PhotoActivity, "Введите название", Toast.LENGTH_SHORT).show() }
                    }
                    .setNegativeButton("Отмена", null).show()
            }
        }
        val tags = styledEdit(p.tags.joinToString(", "), "Теги через запятую")
        val note = styledEdit(p.note, "Заметка")
        box.addView(name); box.addView(album); box.addView(newAlbum); box.addView(tags); box.addView(note)
        AlertDialog.Builder(this).setTitle("Изменить фото").setView(box)
            .setPositiveButton("Сохранить") { _, _ ->
                p.name = name.text.toString().ifBlank { p.name }
                p.album = album.selectedItem?.toString().orEmpty().ifBlank { "Разное" }
                p.tags = tags.text.toString().split(",").map { it.trim().trimStart('#') }.filter { it.isNotEmpty() }.toMutableList()
                p.note = note.text.toString()
                PhotoStore.update(this, p); renderText()
            }
            .setNegativeButton("Отмена", null).show()
    }
}
