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
    private var fullscreen: Boolean = false
    private var mediaController: android.widget.MediaController? = null
    private val autoHideHandler = android.os.Handler(android.os.Looper.getMainLooper())
    private val autoHideRunnable = Runnable { hideFullscreenChrome() }

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
        zoom.onSingleTap = { setFullscreen(!fullscreen) }
        zoom.onLongPressPhoto = { showPhotoActions() }
        findViewById<TextView>(R.id.prevBtn).setOnClickListener { move(-1) }
        findViewById<TextView>(R.id.nextBtn).setOnClickListener { move(1) }
        val videoView = findViewById<android.widget.VideoView>(R.id.videoPlayer)
        videoView.setOnTouchListener { _, event ->
            if (event.action == android.view.MotionEvent.ACTION_UP) {
                if (!fullscreen) setFullscreen(true) else { showFullscreenChrome(); mediaController?.show(2000) }
            }
            false
        }

        findViewById<Button>(R.id.pinBtn).setOnClickListener {
            val current = photo ?: run { finish(); return }@setOnClickListener
            if (current.widgetId > 0) {
                // Старые независимые копии v1.6: удаление такой записи не трогает оригинал.
                AlertDialog.Builder(this).setTitle("Убрать старую копию из виджета №${current.widgetId}?")
                    .setPositiveButton("Убрать") { _, _ ->
                        PhotoStore.delete(this, current); PinnedPhotoWidgetBase.updateAll(this); finish()
                    }.setNegativeButton("Отмена", null).show()
            } else chooseWidgetsForCurrent(current)
        }
        findViewById<Button>(R.id.shareBtn).setOnClickListener { photo?.let { share(it) } }
        findViewById<Button>(R.id.copyBtn).setOnClickListener { photo?.let { copy(it) } }
        findViewById<Button>(R.id.editBtn).setOnClickListener { photo?.let { edit(it) } }
        findViewById<Button>(R.id.deleteBtn).setOnClickListener {
            val current = photo ?: run { finish(); return }@setOnClickListener
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
        val current = photo ?: run { finish(); return }
        val video = findViewById<android.widget.VideoView>(R.id.videoPlayer)
        val image = findViewById<ZoomImageView>(R.id.fullImage)
        if (current.mime.startsWith("video/")) {
            image.visibility = android.view.View.GONE; video.visibility = android.view.View.VISIBLE
            val plain = PhotoStore.plainBytes(this, current)
            if (plain != null) {
                val temp = java.io.File(cacheDir, "play_${current.id}.mp4").apply { writeBytes(plain) }
                video.setVideoPath(temp.absolutePath)
                mediaController = android.widget.MediaController(this).apply { setAnchorView(video) }
                video.setMediaController(mediaController)
                video.setOnPreparedListener { it.isLooping = true; video.start() }
            }
        } else {
            if (video.isPlaying) video.stopPlayback(); video.visibility = android.view.View.GONE; image.visibility = android.view.View.VISIBLE
            image.setImageBitmap(PhotoStore.decodeBitmap(this, current, 1400))
        }
        findViewById<TextView>(R.id.positionText).text = "${index + 1} / ${ids.size}"
        renderText()
    }

    private fun move(delta: Int) {
        if (ids.size <= 1) return
        index = ((index + delta) % ids.size + ids.size) % ids.size
        loadCurrent(); showFullscreenChrome()
    }

    private fun chromeViews(): List<android.view.View> = listOf(
        findViewById(R.id.prevBtn), findViewById(R.id.nextBtn),
        findViewById(R.id.positionText), findViewById(R.id.fullscreenCaption)
    )

    private fun showFullscreenChrome() {
        if (!fullscreen) return
        chromeViews().forEach { it.visibility = android.view.View.VISIBLE }
        autoHideHandler.removeCallbacks(autoHideRunnable)
        autoHideHandler.postDelayed(autoHideRunnable, 2000)
        val current = photo
        if (current?.mime?.startsWith("video/") == true) mediaController?.show(2000)
    }

    private fun hideFullscreenChrome() {
        if (!fullscreen) return
        chromeViews().forEach { it.visibility = android.view.View.GONE }
        mediaController?.hide()
    }

    override fun onPause() {
        autoHideHandler.removeCallbacks(autoHideRunnable)
        val video = findViewById<android.widget.VideoView>(R.id.videoPlayer)
        if (video.isPlaying) video.pause()
        super.onPause()
    }

    override fun onDestroy() {
        autoHideHandler.removeCallbacks(autoHideRunnable)
        super.onDestroy()
    }

    private fun setFullscreen(enabled: Boolean) {
        fullscreen = enabled
        findViewById<android.view.View>(R.id.bottomPanel).visibility = if (enabled) android.view.View.GONE else android.view.View.VISIBLE
        findViewById<android.view.View>(R.id.fullscreenCaption).visibility = if (enabled) android.view.View.VISIBLE else android.view.View.GONE
        if (enabled) showFullscreenChrome() else {
            autoHideHandler.removeCallbacks(autoHideRunnable)
            chromeViews().forEach { it.visibility = android.view.View.VISIBLE }
            findViewById<android.view.View>(R.id.fullscreenCaption).visibility = android.view.View.GONE
        }
        if (enabled) {
            @Suppress("DEPRECATION")
            window.decorView.systemUiVisibility = (
                android.view.View.SYSTEM_UI_FLAG_FULLSCREEN or
                android.view.View.SYSTEM_UI_FLAG_HIDE_NAVIGATION or
                android.view.View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY or
                android.view.View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN or
                android.view.View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
            )
        } else {
            @Suppress("DEPRECATION") window.decorView.systemUiVisibility = android.view.View.SYSTEM_UI_FLAG_VISIBLE
        }
        findViewById<ZoomImageView>(R.id.fullImage).refreshForResize()
        window.decorView.post { findViewById<ZoomImageView>(R.id.fullImage).refreshForResize() }
        renderText()
    }

    private fun chooseWidgetsForCurrent(current: Photo) {
        val widgetIds = PinnedPhotoWidgetBase.installedWidgetIds(this)
        if (widgetIds.isEmpty()) {
            Toast.makeText(this, "Виджет не добавлен на рабочий стол — кнопка пока не работает", Toast.LENGTH_LONG).show(); return
        }
        if (widgetIds.size == 1) {
            val added = PinnedPhotoWidgetBase.addCopiesToWidgets(this, listOf(current.id), widgetIds)
            PinnedPhotoWidgetBase.updateAll(this)
            Toast.makeText(this, if (added > 0) "Фото добавлено в единственный виджет" else "Это фото уже есть в виджете", Toast.LENGTH_LONG).show(); renderText(); return
        }
        val containing = PinnedPhotoWidgetBase.widgetsContaining(this, current.id)
        val labels = widgetIds.map { if (it in containing) "${PinnedPhotoWidgetBase.widgetName(this, it)} · уже там ✓" else PinnedPhotoWidgetBase.widgetName(this, it) }.toTypedArray()
        val checked = BooleanArray(widgetIds.size) { widgetIds[it] in containing }
        AlertDialog.Builder(this).setTitle("Добавить копию в виджеты")
            .setMultiChoiceItems(labels, checked) { _, which, isChecked -> checked[which] = isChecked }
            .setPositiveButton("Добавить") { _, _ ->
                val chosen = widgetIds.filterIndexed { index, _ -> checked[index] }
                PinnedPhotoWidgetBase.setPhotoWidgets(this, current.id, chosen)
                PinnedPhotoWidgetBase.updateAll(this); renderText()
                Toast.makeText(this, if (chosen.isEmpty()) "Фото убрано из всех виджетов" else "Виджеты обновлены: ${chosen.size}", Toast.LENGTH_SHORT).show()
            }
            .setNeutralButton("Во все") { _, _ ->
                PinnedPhotoWidgetBase.setPhotoWidgets(this, current.id, widgetIds)
                PinnedPhotoWidgetBase.updateAll(this); renderText(); Toast.makeText(this, "Фото добавлено во все виджеты", Toast.LENGTH_SHORT).show()
            }
            .setNegativeButton("Отмена", null).show()
    }

    private fun showPhotoActions() {
        val p = photo ?: return
        val labels = arrayOf(
            if (p.pinned) "📌 Открепить" else "📌 Закрепить",
            "Поделиться", "Копировать", "Изменить", "Удалить"
        )
        AlertDialog.Builder(this)
            .setTitle(p.name)
            .setItems(labels) { _, which ->
                when (which) {
                    0 -> findViewById<Button>(R.id.pinBtn).performClick()
                    1 -> findViewById<Button>(R.id.shareBtn).performClick()
                    2 -> findViewById<Button>(R.id.copyBtn).performClick()
                    3 -> findViewById<Button>(R.id.editBtn).performClick()
                    4 -> findViewById<Button>(R.id.deleteBtn).performClick()
                }
            }
            .setNegativeButton("Отмена", null)
            .show()
    }

    @Deprecated("назад сначала выходит из полного экрана")
    override fun onBackPressed() {
        if (fullscreen) setFullscreen(false) else super.onBackPressed()
    }

    private fun renderText() {
        val p = photo ?: return
        findViewById<TextView>(R.id.photoName).text = p.name
        val saved = java.text.SimpleDateFormat("dd.MM.yyyy · HH:mm", java.util.Locale.getDefault()).format(java.util.Date(p.createdAt))
        val meta = listOf("Сохранено: $saved", p.albums.joinToString(", "), p.tags.joinToString(" ") { "#$it" }, p.note)
            .filter { it.isNotBlank() }.joinToString(" · ")
        findViewById<TextView>(R.id.photoMeta).text = meta
        findViewById<Button>(R.id.pinBtn).text = when {
            p.widgetId > 0 -> "🧩 Старая копия виджета №${p.widgetId}"
            PinnedPhotoWidgetBase.installedWidgetIds(this).isEmpty() -> "В виджет (нет виджета)"
            p.id in PinnedPhotoWidgetBase.installedWidgetIds(this).flatMap { PinnedPhotoWidgetBase.getWidgetPhotoIds(this, it) } -> "В виджете ✓"
            else -> "В виджет"
        }
        findViewById<TextView>(R.id.fullName).text = p.name
        findViewById<TextView>(R.id.fullMeta).text = meta
    }

    private fun sharedUri(p: Photo): Uri {
        val src = p.fileIn(PhotoStore.dir(this))
        val dir = File(cacheDir, "shared").apply { mkdirs() }
        val ext = src.extension.ifBlank { "jpg" }
        val out = File(dir, "${p.name.replace(Regex("[^A-Za-z0-9А-Яа-яЁё _-]"), "_")}.$ext")
        val plain = PhotoStore.plainBytes(this, p) ?: throw IllegalStateException("Не удалось прочитать фото")
        out.writeBytes(plain)
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
        val displayAlbums = albumNames.toMutableList() // «Разное» уже есть первым и заменяет «Без альбома»
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
            setSelection(if (p.album.isBlank()) displayAlbums.indexOf(PhotoStore.MISC_ALBUM).coerceAtLeast(0) else displayAlbums.indexOf(p.album).coerceAtLeast(0))
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
                            displayAlbums.clear(); displayAlbums.addAll(PhotoStore.albums(this@PhotoActivity))
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
                p.albums = mutableListOf(album.selectedItem?.toString()?.takeIf { it.isNotBlank() } ?: PhotoStore.MISC_ALBUM)
                p.tags = tags.text.toString().split(",").map { it.trim().trimStart('#') }.filter { it.isNotEmpty() }.toMutableList()
                p.note = note.text.toString()
                PhotoStore.update(this, p); renderText()
            }
            .setNegativeButton("Отмена", null).show()
    }
}
