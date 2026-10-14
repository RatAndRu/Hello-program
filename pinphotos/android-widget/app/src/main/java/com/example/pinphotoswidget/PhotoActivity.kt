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

    private fun share(p: Photo) {
        try {
            val src = p.fileIn(PhotoStore.dir(this))
            val dir = File(cacheDir, "shared").apply { mkdirs() }
            val ext = src.extension.ifBlank { "jpg" }
            val out = File(dir, "${p.name.replace(Regex("[^A-Za-z0-9А-Яа-яЁё _-]"), "_")}.$ext")
            src.copyTo(out, overwrite = true)
            val uri = FileProvider.getUriForFile(this, packageName + ".fileprovider", out)
            startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).apply {
                type = p.mime; putExtra(Intent.EXTRA_STREAM, uri)
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            }, "Поделиться"))
        } catch (e: Exception) {
            Toast.makeText(this, "Не удалось поделиться: ${e.message}", Toast.LENGTH_LONG).show()
        }
    }

    private fun edit(p: Photo) {
        val box = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(48, 24, 48, 8) }
        val name = EditText(this).apply { setText(p.name); hint = "Название" }
        val album = EditText(this).apply { setText(p.album); hint = "Альбом" }
        val tags = EditText(this).apply { setText(p.tags.joinToString(", ")); hint = "Теги через запятую" }
        val note = EditText(this).apply { setText(p.note); hint = "Заметка" }
        box.addView(name); box.addView(album); box.addView(tags); box.addView(note)
        AlertDialog.Builder(this).setTitle("Фото").setView(box)
            .setPositiveButton("Сохранить") { _, _ ->
                p.name = name.text.toString().ifBlank { p.name }
                p.album = album.text.toString().ifBlank { "Разное" }
                p.tags = tags.text.toString().split(",").map { it.trim().trimStart('#') }.filter { it.isNotEmpty() }.toMutableList()
                p.note = note.text.toString()
                PhotoStore.update(this, p); renderText()
            }
            .setNegativeButton("Отмена", null).show()
    }
}
