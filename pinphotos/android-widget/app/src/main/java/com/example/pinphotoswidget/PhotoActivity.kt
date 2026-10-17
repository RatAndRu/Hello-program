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
    private var fullscreenChromeVisible: Boolean = false
    private val autoHideHandler = android.os.Handler(android.os.Looper.getMainLooper())
    private val autoHideRunnable = Runnable { hideFullscreenChrome() }
    private var slideshowSeconds: Int = 0
    private var currentMediaPlayer: android.media.MediaPlayer? = null
    private val slideshowHandler = android.os.Handler(android.os.Looper.getMainLooper())
    private val slideshowRunnable = Runnable {
        if (fullscreen && slideshowSeconds > 0) move(1)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        UiTheme.apply(this)
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_photo)
        ids = savedInstanceState?.getStringArrayList("ids") ?: intent.getStringArrayListExtra("ids") ?: arrayListOf()
        if (ids.isEmpty()) intent.getStringExtra("id")?.let { ids = listOf(it) }
        if (ids.isEmpty()) return finish()
        index = (savedInstanceState?.getInt("index") ?: intent.getIntExtra("index", 0)).coerceIn(0, ids.lastIndex)
        fullscreen = savedInstanceState?.getBoolean("fullscreen") ?: false
        slideshowSeconds = getSharedPreferences("slideshow", Context.MODE_PRIVATE).getInt("seconds", 0)
        try { loadCurrent() } catch (e: Throwable) { showLoadError(e) }
        if (fullscreen) {
            findViewById<android.view.View>(R.id.bottomPanel).visibility = android.view.View.GONE
            applyFullscreenSystemUi()
        }

        val zoom = findViewById<ZoomImageView>(R.id.fullImage)
        zoom.onHorizontalSwipe = { delta -> move(delta) }
        zoom.onSingleTap = { setFullscreen(!fullscreen) }
        zoom.onLongPressPhoto = { showPhotoActions() }
        findViewById<TextView>(R.id.slideshowBtn).setOnClickListener { showSlideshowDialog() }
        findViewById<TextView>(R.id.prevBtn).setOnClickListener { move(-1) }
        findViewById<TextView>(R.id.nextBtn).setOnClickListener { move(1) }
        val videoView = findViewById<android.widget.VideoView>(R.id.videoPlayer)
        videoView.setOnTouchListener { _, event ->
            if (event.action == android.view.MotionEvent.ACTION_UP) {
                val controllerShowing = mediaController?.isShowing == true
                when {
                    // 1-й тап в обычном режиме: показать контролы на 3 секунды.
                    // 2-й тап, пока контролы ещё видны: перейти в полный экран.
                    !fullscreen && controllerShowing -> setFullscreen(true)
                    !fullscreen -> mediaController?.show(3000)
                    // Полный экран: скрытый интерфейс показать, видимый — по тапу выходим.
                    !fullscreenChromeVisible -> showFullscreenChrome()
                    else -> setFullscreen(false)
                }
            }
            // true: не даём VideoView самому тут же переключить/спрятать контроллер своим обработчиком тапа.
            true
        }
        findViewById<Button>(R.id.pinBtn).setOnClickListener {
            val current = photo ?: return@setOnClickListener
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
        slideshowHandler.removeCallbacks(slideshowRunnable)
        val all = PhotoStore.list(this)
        photo = all.firstOrNull { it.id == ids[index] }
        val current = photo ?: run { finish(); return }
        val video = findViewById<android.widget.VideoView>(R.id.videoPlayer)
        val image = findViewById<ZoomImageView>(R.id.fullImage)
        if (current.mime.startsWith("video/")) {
            image.visibility = android.view.View.GONE; video.visibility = android.view.View.VISIBLE
            val playable = PhotoStore.playableFile(this, current)
            if (playable != null) {
                video.setVideoPath(playable.absolutePath)
                mediaController = android.widget.MediaController(this).apply { setAnchorView(video) }
                video.setMediaController(mediaController)
                video.setOnPreparedListener {
                    currentMediaPlayer = it
                    // В полном экране при включённом слайд-шоу видео не зацикливаем.
                    applyVideoLooping()
                    video.start()
                    if (fullscreen) showFullscreenChrome() else mediaController?.show(3000)
                }
                video.setOnErrorListener { _, what, extra ->
                    try { java.io.File(cacheDir, "video_error.txt").writeText("what=$what extra=$extra file=${current.file}") } catch (ignored: Exception) { }
                    Toast.makeText(this, "Не удалось воспроизвести это видео", Toast.LENGTH_SHORT).show()
                    if (fullscreen && slideshowSeconds > 0) {
                        slideshowHandler.postDelayed({ if (fullscreen && !isFinishing) move(1) }, 600)
                    }
                    true
                }
                video.setOnCompletionListener {
                    // По просьбе: в слайд-шоу переключаемся СРАЗУ по окончании видео, без периода.
                    // Перемотка пользователем ничего не ломает: completion придёт по фактическому концу.
                    if (fullscreen && slideshowSeconds > 0) move(1)
                }
            }
        } else {
            if (video.isPlaying) video.stopPlayback(); video.visibility = android.view.View.GONE; image.visibility = android.view.View.VISIBLE
            image.setImageBitmap(PhotoStore.decodeBitmap(this, current, 1400))
        }
        // У видео подпись в полном экране — сверху, чтобы не накладывалась на перемотку/паузу снизу.
        val caption = findViewById<android.view.View>(R.id.fullscreenCaption)
        (caption.layoutParams as? android.widget.FrameLayout.LayoutParams)?.let { lp ->
            if (current.mime.startsWith("video/")) {
                lp.gravity = android.view.Gravity.TOP; lp.topMargin = dp(56); lp.bottomMargin = 0
            } else {
                lp.gravity = android.view.Gravity.BOTTOM; lp.topMargin = 0; lp.bottomMargin = dp(10)
            }
            caption.layoutParams = lp
        }
        findViewById<TextView>(R.id.positionText).text = "${index + 1} / ${ids.size}"
        // Слайд-шоу не должно сбрасывать полный экран при переходе фото -> видео.
        findViewById<android.view.View>(R.id.bottomPanel).visibility =
            if (fullscreen) android.view.View.GONE else android.view.View.VISIBLE
        if (fullscreen) {
            applyFullscreenSystemUi()
            // VideoView/MediaController на ряде оболочек сбрасывают immersive-флаги после старта.
            window.decorView.postDelayed({ if (fullscreen && !isFinishing) applyFullscreenSystemUi() }, 300)
        }
        renderText(); schedulePhotoSlideshow()
    }

    private fun applyVideoLooping() {
        // Loop допустим только когда слайд-шоу выключено или мы не в полном экране.
        currentMediaPlayer?.isLooping = !(fullscreen && slideshowSeconds > 0)
    }

    private fun schedulePhotoSlideshow() {
        slideshowHandler.removeCallbacks(slideshowRunnable)
        val current = photo ?: return
        if (fullscreen && slideshowSeconds > 0 && !current.mime.startsWith("video/")) {
            slideshowHandler.postDelayed(slideshowRunnable, slideshowSeconds * 1000L)
        }
    }

    private fun showSlideshowDialog() {
        val options = listOf(0, 3, 5, 10, 30, 60)
        val labels = arrayOf("Выключено", "Каждые 3 секунды", "Каждые 5 секунд", "Каждые 10 секунд", "Каждые 30 секунд", "Каждую минуту")
        val checked = options.indexOf(slideshowSeconds).coerceAtLeast(0)
        AlertDialog.Builder(this).setTitle("Слайд-шоу в полном экране")
            .setSingleChoiceItems(labels, checked) { dialog, which ->
                slideshowSeconds = options[which]
                getSharedPreferences("slideshow", Context.MODE_PRIVATE).edit().putInt("seconds", slideshowSeconds).apply()
                dialog.dismiss(); renderText(); showFullscreenChrome(); applyVideoLooping(); schedulePhotoSlideshow()
                val video = findViewById<android.widget.VideoView>(R.id.videoPlayer)
                if (photo?.mime?.startsWith("video/") == true && slideshowSeconds > 0 && fullscreen &&
                    video.duration > 0 && video.currentPosition >= video.duration - 500) {
                    move(1)
                } else if (photo?.mime?.startsWith("video/") == true && !video.isPlaying) video.start()
                Toast.makeText(this, if (slideshowSeconds == 0) "Слайд-шоу выключено" else "Слайд-шоу: ${labels[which]}", Toast.LENGTH_SHORT).show()
            }
            .setNegativeButton("Отмена", null).show()
    }

    private fun move(delta: Int) {
        if (ids.size <= 1) return
        index = ((index + delta) % ids.size + ids.size) % ids.size
        try { loadCurrent() } catch (e: Throwable) { showLoadError(e); return }
        if (fullscreen) applyFullscreenSystemUi()
        showFullscreenChrome()
    }

    private fun chromeViews(): List<android.view.View> = listOf(
        findViewById(R.id.prevBtn), findViewById(R.id.nextBtn),
        findViewById(R.id.positionText), findViewById(R.id.fullscreenCaption),
        findViewById(R.id.slideshowBtn)
    )

    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()

    private fun showFullscreenChrome() {
        if (!fullscreen) return
        fullscreenChromeVisible = true
        chromeViews().forEach { it.visibility = android.view.View.VISIBLE }
        autoHideHandler.removeCallbacks(autoHideRunnable)
        autoHideHandler.postDelayed(autoHideRunnable, 2000)
        val current = photo
        if (current?.mime?.startsWith("video/") == true) mediaController?.show(2000)
    }

    private fun hideFullscreenChrome() {
        if (!fullscreen) return
        fullscreenChromeVisible = false
        chromeViews().forEach { it.visibility = android.view.View.GONE }
        mediaController?.hide()
    }

    override fun onSaveInstanceState(outState: Bundle) {
        outState.putStringArrayList("ids", ArrayList(ids))
        outState.putInt("index", index)
        outState.putBoolean("fullscreen", fullscreen)
        super.onSaveInstanceState(outState)
    }

    private fun showLoadError(error: Throwable) {
        try { java.io.File(filesDir, "last_crash.txt").writeText(android.util.Log.getStackTraceString(error)) } catch (ignored: Exception) { }
        Toast.makeText(this, "Не удалось открыть файл: ${error.message ?: "ошибка"}", Toast.LENGTH_LONG).show()
    }

    private fun applyFullscreenSystemUi() {
        @Suppress("DEPRECATION")
        window.decorView.systemUiVisibility = (
            android.view.View.SYSTEM_UI_FLAG_FULLSCREEN or
            android.view.View.SYSTEM_UI_FLAG_HIDE_NAVIGATION or
            android.view.View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY or
            android.view.View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN or
            android.view.View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
        )
    }

    override fun onPause() {
        slideshowHandler.removeCallbacks(slideshowRunnable)
        autoHideHandler.removeCallbacks(autoHideRunnable)
        val video = findViewById<android.widget.VideoView>(R.id.videoPlayer)
        if (video.isPlaying) video.pause()
        super.onPause()
    }

    override fun onDestroy() {
        slideshowHandler.removeCallbacks(slideshowRunnable)
        autoHideHandler.removeCallbacks(autoHideRunnable)
        super.onDestroy()
    }

    private fun setFullscreen(enabled: Boolean) {
        fullscreen = enabled
        applyVideoLooping()
        if (!enabled) slideshowHandler.removeCallbacks(slideshowRunnable)
        findViewById<android.view.View>(R.id.slideshowBtn).visibility = if (enabled) android.view.View.VISIBLE else android.view.View.GONE
        findViewById<android.view.View>(R.id.bottomPanel).visibility = if (enabled) android.view.View.GONE else android.view.View.VISIBLE
        findViewById<android.view.View>(R.id.fullscreenCaption).visibility = if (enabled) android.view.View.VISIBLE else android.view.View.GONE
        if (enabled) showFullscreenChrome() else {
            fullscreenChromeVisible = false
            autoHideHandler.removeCallbacks(autoHideRunnable)
            chromeViews().forEach { it.visibility = android.view.View.VISIBLE }
            findViewById<android.view.View>(R.id.slideshowBtn).visibility = android.view.View.GONE
            findViewById<android.view.View>(R.id.fullscreenCaption).visibility = android.view.View.GONE
            if (photo?.mime?.startsWith("video/") == true) mediaController?.show(3000)
        }
        if (enabled) {
            applyFullscreenSystemUi()
        } else {
            @Suppress("DEPRECATION") window.decorView.systemUiVisibility = android.view.View.SYSTEM_UI_FLAG_VISIBLE
        }
        findViewById<ZoomImageView>(R.id.fullImage).refreshForResize()
        window.decorView.post { findViewById<ZoomImageView>(R.id.fullImage).refreshForResize() }
        renderText(); schedulePhotoSlideshow()
    }

    private fun chooseWidgetsForCurrent(current: Photo) {
        val widgetIds = PinnedPhotoWidgetBase.installedWidgetIds(this)
        if (widgetIds.isEmpty()) {
            Toast.makeText(this, "Виджет не добавлен на рабочий стол — кнопка пока не работает", Toast.LENGTH_LONG).show(); return
        }
        if (widgetIds.size == 1) {
            val onlyWidget = widgetIds.first()
            if (current.id in PinnedPhotoWidgetBase.getWidgetPhotoIds(this, onlyWidget)) {
                // Повторное нажатие при единственном виджете — убрать фото из него.
                PinnedPhotoWidgetBase.setPhotoWidgets(this, current.id, emptyList())
                PinnedPhotoWidgetBase.updateAll(this)
                Toast.makeText(this, "Фото убрано из виджета", Toast.LENGTH_SHORT).show()
            } else {
                PinnedPhotoWidgetBase.addCopiesToWidgets(this, listOf(current.id), widgetIds)
                PinnedPhotoWidgetBase.updateAll(this)
                Toast.makeText(this, "Фото добавлено в единственный виджет", Toast.LENGTH_SHORT).show()
            }
            renderText(); return
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
        findViewById<TextView>(R.id.slideshowBtn).text = if (slideshowSeconds > 0) "↻ ${slideshowSeconds}с" else "↻"
        findViewById<TextView>(R.id.slideshowBtn).textSize = if (slideshowSeconds > 0) 13f else 22f
        findViewById<TextView>(R.id.fullName).text = p.name
        findViewById<TextView>(R.id.fullMeta).text = meta
    }

    private fun sharedUri(p: Photo): Uri {
        val src = p.fileIn(PhotoStore.dir(this))
        val dir = File(cacheDir, "shared").apply { mkdirs() }
        val ext = src.extension.ifBlank { "jpg" }
        val out = File(dir, "${p.name.replace(Regex("[^A-Za-z0-9А-Яа-яЁё _-]"), "_")}.$ext")
        if (!PhotoStore.copyPlainTo(this, p, out)) throw IllegalStateException("Не удалось прочитать фото")
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
