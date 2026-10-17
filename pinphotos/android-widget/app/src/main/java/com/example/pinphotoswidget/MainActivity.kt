package com.example.pinphotoswidget

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
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricPrompt
import androidx.core.content.ContextCompat
import androidx.fragment.app.FragmentActivity
import androidx.recyclerview.widget.GridLayoutManager
import androidx.recyclerview.widget.RecyclerView
import org.json.JSONObject
import java.io.File
import java.util.concurrent.Executors

/** Полностью нативное приложение «ЗакрепФото» (без WebView): сетка фото, импорт, виджет, иконки. */
class MainActivity : FragmentActivity() {
    private lateinit var grid: RecyclerView
    private lateinit var emptyView: View
    private lateinit var countText: TextView
    private var photos: MutableList<Photo> = mutableListOf()
    private var selectedAlbum: String = ALL_ALBUMS
    private var pendingImportAlbum: String = ""
    private var pendingImportWidget: Int = 0
    private var searchQuery: String = ""
    private var sortMode: Int = 0
    private var albumsModeWidgets: Boolean = false
    private var albumsCollapsed: Boolean = false
    private var searchExpanded: Boolean = false
    private var selectionForcedAlbumsCollapse: Boolean = false
    private var lastWidgetSignature: String? = null
    private val selectedIds = linkedSetOf<String>()
    private val unlockedAlbums = mutableSetOf<String>()
    private val io = Executors.newFixedThreadPool(3)

    override fun onCreate(savedInstanceState: Bundle?) {
        UiTheme.apply(this)
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        grid = findViewById(R.id.grid)
        emptyView = findViewById(R.id.emptyView)
        countText = findViewById(R.id.countText)
        grid.layoutManager = GridLayoutManager(this, 3)
        findViewById<Button>(R.id.importBtn).setOnClickListener { importPressed() }
        findViewById<Button>(R.id.emptyImportBtn).setOnClickListener { importPressed() }
        findViewById<View>(R.id.menuBtn).setOnClickListener { showMenu(it) }
        findViewById<View>(R.id.exitBtn).setOnClickListener { finishAndRemoveTask() }
        findViewById<Button>(R.id.moveSelectedBtn).setOnClickListener { chooseMoveAlbum() }
        findViewById<Button>(R.id.clearSelectionBtn).setOnClickListener { selectedIds.clear(); refresh() }
        findViewById<Button>(R.id.widgetSelectedBtn).setOnClickListener { chooseWidgetsForPhotos(selectedIds.toList()) }
        findViewById<Button>(R.id.shareSelectedBtn).setOnClickListener { shareSelected() }
        findViewById<Button>(R.id.deleteSelectedBtn).setOnClickListener { confirmDeleteSelected() }
        val search = findViewById<android.widget.EditText>(R.id.searchInput)
        search.addTextChangedListener(object : android.text.TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, a: Int, b: Int, c: Int) {}
            override fun onTextChanged(s: CharSequence?, a: Int, b: Int, c: Int) { searchQuery = s?.toString().orEmpty().trim(); refresh() }
            override fun afterTextChanged(s: android.text.Editable?) {}
        })
        findViewById<View>(R.id.filterBtn).setOnClickListener { showFilters() }
        findViewById<View>(R.id.searchBtn).setOnClickListener { setSearchExpanded(!searchExpanded) }
        findViewById<Button>(R.id.albumsModeBtn).setOnClickListener {
            albumsModeWidgets = !albumsModeWidgets
            // Переключение режима не меняет текущую открытую выборку резко: возвращаемся во «Все фото».
            selectedAlbum = ALL_ALBUMS; refresh()
        }
        findViewById<Button>(R.id.albumsCollapseBtn).setOnClickListener {
            albumsCollapsed = !albumsCollapsed; applyAlbumsCollapsed()
        }
    }

    override fun onResume() { super.onResume(); refresh() }

    private fun setSearchExpanded(expanded: Boolean) {
        searchExpanded = expanded
        findViewById<View>(R.id.appTitle).visibility = if (expanded) View.GONE else View.VISIBLE
        val input = findViewById<android.widget.EditText>(R.id.searchInput)
        input.visibility = if (expanded) View.VISIBLE else View.GONE
        if (expanded) {
            input.requestFocus()
            val imm = getSystemService(android.content.Context.INPUT_METHOD_SERVICE) as android.view.inputmethod.InputMethodManager
            imm.showSoftInput(input, android.view.inputmethod.InputMethodManager.SHOW_IMPLICIT)
        } else if (searchQuery.isNotEmpty()) {
            input.text.clear()
        }
        refresh()
    }

    private fun showFilters() {
        val labels = arrayOf("Сначала новые", "Сначала старые", "По алфавиту А–Я", "По алфавиту Я–А")
        val dialog = android.app.AlertDialog.Builder(this)
            .setTitle("Сортировка")
            .setSingleChoiceItems(labels, sortMode) { d, which -> sortMode = which; d.dismiss(); refresh() }
            .setNegativeButton("Отмена", null)
            .create()
        dialog.show()
        // Скруглённое окно выпадающего списка фильтров, а не квадратный системный прямоугольник.
        dialog.window?.setBackgroundDrawableResource(if (UiTheme.isDark(this)) R.drawable.dialog_bg_dark else R.drawable.dialog_bg_light)
    }

    private fun applyAlbumsCollapsed() {
        findViewById<View>(R.id.albumsContent).visibility = if (albumsCollapsed) View.GONE else View.VISIBLE
        findViewById<Button>(R.id.albumsCollapseBtn).text = if (albumsCollapsed) "▸  Альбомы" else "▾  Альбомы"
    }


    private fun refresh() {
        photos = PhotoStore.list(this)
        val lockedNames = PhotoStore.lockedAlbumNames(this)
        val ordinaryPhotos = photos.filter { it.widgetId == 0 }
        val visiblePhotos = ordinaryPhotos.filter { photo ->
            PhotoStore.MISC_ALBUM in photo.albums && photo.albums.none { it in lockedNames }
        }
        val widgetIdsNow = PinnedPhotoWidgetBase.installedWidgetIds(this)
        val widgetPhotosCount = widgetIdsNow.sumOf { PinnedPhotoWidgetBase.getWidgetPhotoIds(this, it).size }
        val pinnedCount = if (widgetPhotosCount > 0) widgetPhotosCount else visiblePhotos.count { it.pinned }
        renderAlbums()
        val baseDisplayed = when {
            selectedAlbum.startsWith(WIDGET_PREFIX) -> PinnedPhotoWidgetBase.photosForWidget(this, selectedWidgetId())
            selectedAlbum == ALL_ALBUMS -> visiblePhotos
            else -> ordinaryPhotos.filter { selectedAlbum in it.albums }
        }
        val searched = if (searchQuery.isBlank()) baseDisplayed else baseDisplayed.filter { photo ->
            val q = searchQuery.lowercase()
            photo.name.lowercase().contains(q) || photo.tags.any { tag -> tag.lowercase().contains(q.removePrefix("#")) }
        }
        val displayedDeduped = PhotoStore.dedupeForDisplay(searched)
        val displayed = when (sortMode) {
            1 -> displayedDeduped.sortedBy { it.createdAt }
            2 -> displayedDeduped.sortedBy { it.name.lowercase() }
            3 -> displayedDeduped.sortedByDescending { it.name.lowercase() }
            else -> displayedDeduped.sortedByDescending { it.createdAt }
        }
        // В шапке — количество именно найденных/показанных фото.
        countText.text = if (displayed.isEmpty()) "" else "${displayed.size}"
        selectedIds.retainAll(photos.map { it.id }.toSet())
        emptyView.visibility = if (displayed.isEmpty()) View.VISIBLE else View.GONE
        grid.visibility = if (displayed.isEmpty()) View.GONE else View.VISIBLE
        findViewById<TextView>(R.id.emptyText).text = when {
            displayed.isEmpty() && searchQuery.isNotBlank() -> "По запросу «$searchQuery» ничего не нашлось"
            displayed.isEmpty() && photos.isEmpty() -> "Пока нет фотографий"
            else -> "В этой выборке пока пусто"
        }
        val bar = findViewById<View>(R.id.selectionBar)
        bar.visibility = if (selectedIds.isEmpty()) View.GONE else View.VISIBLE
        findViewById<View>(R.id.selectionActions2).visibility = bar.visibility
        if (selectedIds.isNotEmpty()) findViewById<TextView>(R.id.selectionText).text = "Выбрано: ${selectedIds.size}"
        val widgetPhotoIds = PinnedPhotoWidgetBase.installedWidgetIds(this)
            .flatMap { PinnedPhotoWidgetBase.getWidgetPhotoIds(this, it) }.toSet()
        grid.adapter = PhotoAdapter(displayed, selectedIds, widgetPhotoIds,
            onClick = { photo ->
                if (selectedIds.isNotEmpty()) toggleSelected(photo) else {
                    val ids = ArrayList(displayed.map { it.id })
                    startActivity(Intent(this, PhotoActivity::class.java)
                        .putStringArrayListExtra("ids", ids)
                        .putExtra("index", displayed.indexOf(photo)))
                }
            },
            onLongClick = { photo -> toggleSelected(photo) }
        )
        findViewById<TextView>(R.id.albumsTitle).text = if (albumsModeWidgets) "Альбомы виджетов" else "Альбомы"
        findViewById<Button>(R.id.albumsModeBtn).text = if (albumsModeWidgets) "Обычные 📁" else "Виджеты 🧩"
        // При выделении фото панель альбомов временно сворачиваем; после снятия выделения
        // возвращаем её только если до выделения она была развёрнута.
        if (selectedIds.isNotEmpty() && !albumsCollapsed) {
            selectionForcedAlbumsCollapse = true; albumsCollapsed = true
        } else if (selectedIds.isEmpty() && selectionForcedAlbumsCollapse) {
            selectionForcedAlbumsCollapse = false; albumsCollapsed = false
        }
        applyAlbumsCollapsed()
        val widgetSignature = buildString {
            append(UiTheme.isDark(this@MainActivity)).append('|')
            append(PinnedPhotoWidgetBase.installedWidgetIds(this@MainActivity).joinToString(",") { id ->
                id.toString() + ":" + PinnedPhotoWidgetBase.widgetName(this@MainActivity, id) + ":" +
                    PinnedPhotoWidgetBase.getWidgetPhotoIds(this@MainActivity, id).joinToString(".")
            })
            append('|').append(photos.filter { it.pinned }.joinToString(".") { it.id })
            append('|').append(PhotoStore.lockedAlbumNames(this@MainActivity).joinToString("."))
        }
        if (widgetSignature != lastWidgetSignature) {
            lastWidgetSignature = widgetSignature
            try { PinnedPhotoWidgetBase.updateAll(this) } catch (e: Exception) {
                // Виджет — не повод ронять главное окно (например, при быстрой смене темы).
            }
        }
    }

    private fun toggleSelected(photo: Photo) {
        if (!selectedIds.add(photo.id)) selectedIds.remove(photo.id)
        refresh()
    }

    private fun renderAlbums() {
        findViewById<TextView>(R.id.currentAlbumText).text = when {
            selectedAlbum == ALL_ALBUMS -> PhotoStore.MISC_ALBUM
            selectedAlbum.startsWith(WIDGET_PREFIX) -> PinnedPhotoWidgetBase.widgetName(this, selectedWidgetId())
            else -> selectedAlbum
        }
        val row = findViewById<android.widget.LinearLayout>(R.id.albumsTiles)
        row.removeAllViews()
        if (albumsModeWidgets) {
            val widgetIds = PinnedPhotoWidgetBase.installedWidgetIds(this)
            if (widgetIds.isEmpty()) {
                val hint = TextView(this).apply {
                    text = "Виджетов пока нет"; textSize = 13f
                    setTextColor(UiTheme.color(this@MainActivity, R.attr.appMuted)); gravity = android.view.Gravity.CENTER_VERTICAL
                    setPadding(dp(6), 0, dp(8), 0)
                }
                row.addView(hint, 0)
            }
            for (widgetId in widgetIds) row.addView(widgetAlbumTile(widgetId))
            val createWidget = TextView(this).apply {
                text = "＋\nВиджет"; textSize = 15f; gravity = android.view.Gravity.CENTER
                setTextColor(UiTheme.color(this@MainActivity, R.attr.appAccent))
                setBackgroundResource(R.drawable.btn_soft)
                setOnClickListener { showCreateWidgetDialog() }
            }
            row.addView(createWidget, android.widget.LinearLayout.LayoutParams(dp(104), dp(104)).apply { marginEnd = dp(10) })
            return
        }
        val all = photos
        for (album in PhotoStore.albums(this)) {
            val albumPhotos = all.filter { it.widgetId == 0 && album in it.albums }
            row.addView(albumTile(album, albumPhotos))
        }
        // Плитка создания нового альбома
        val create = TextView(this).apply {
            text = "＋\nАльбом"; textSize = 15f; gravity = android.view.Gravity.CENTER
            setTextColor(UiTheme.color(this@MainActivity, R.attr.appAccent))
            setBackgroundResource(R.drawable.btn_soft)
            setOnClickListener { showCreateAlbumDialog { album -> selectedAlbum = album; refresh() } }
        }
        row.addView(create, android.widget.LinearLayout.LayoutParams(dp(104), dp(104)).apply { marginEnd = dp(10) })
        if (PhotoStore.albums(this).isEmpty()) {
            val hint = TextView(this).apply {
                text = "Альбомов пока нет"; textSize = 13f
                setTextColor(UiTheme.color(this@MainActivity, R.attr.appMuted))
                gravity = android.view.Gravity.CENTER_VERTICAL
                setPadding(dp(6), 0, dp(8), 0)
            }
            row.addView(hint, 0)
        }
    }

    private fun widgetAlbumTile(widgetId: Int): View {
        val key = WIDGET_PREFIX + widgetId
        val refs = PinnedPhotoWidgetBase.photosForWidget(this, widgetId)
        val newest = refs.maxByOrNull { it.createdAt }
        val tile = android.widget.FrameLayout(this).apply {
            setBackgroundResource(if (selectedAlbum == key) R.drawable.btn_primary else R.drawable.card_bg)
            clipToOutline = true
            setOnClickListener {
                selectedAlbum = if (selectedAlbum == key) ALL_ALBUMS else key
                refresh()
            }
            setOnLongClickListener { showWidgetAlbumActions(widgetId); true }
        }
        val cover = ImageView(this).apply {
            scaleType = ImageView.ScaleType.CENTER_CROP; setImageResource(R.drawable.widget_placeholder)
        }
        tile.addView(cover, android.widget.FrameLayout.LayoutParams(android.widget.FrameLayout.LayoutParams.MATCH_PARENT, dp(72)))
        if (newest != null) io.execute {
            val bmp = PhotoStore.decodeBitmap(this, newest, 360)
            cover.post { if (bmp != null) cover.setImageBitmap(bmp) }
        }
        val label = TextView(this).apply {
            text = "🧩 ${PinnedPhotoWidgetBase.widgetName(this@MainActivity, widgetId)} · ${refs.size}"
            textSize = 12f; gravity = android.view.Gravity.CENTER
            setTextColor(if (selectedAlbum == key) 0xFFFFFFFF.toInt() else UiTheme.color(this@MainActivity, R.attr.appText))
            setPadding(dp(4), dp(5), dp(4), dp(5))
        }
        tile.addView(label, android.widget.FrameLayout.LayoutParams(
            android.widget.FrameLayout.LayoutParams.MATCH_PARENT,
            android.widget.FrameLayout.LayoutParams.WRAP_CONTENT, android.view.Gravity.BOTTOM))
        tile.layoutParams = android.widget.LinearLayout.LayoutParams(dp(104), dp(104)).apply { marginEnd = dp(10) }
        return tile
    }

    private fun showRenameWidgetDialog(widgetId: Int) {
        val input = themedInput("Название виджета").apply { setText(PinnedPhotoWidgetBase.widgetName(this@MainActivity, widgetId)) }
        val box = android.widget.LinearLayout(this).apply {
            orientation = android.widget.LinearLayout.VERTICAL; setPadding(dp(22), dp(10), dp(22), dp(4)); addView(input)
        }
        android.app.AlertDialog.Builder(this).setTitle("Название виджета").setView(box)
            .setPositiveButton("Сохранить") { _, _ ->
                val name = input.text.toString().trim()
                if (name.isEmpty()) toast("Введите название") else { PinnedPhotoWidgetBase.setWidgetName(this, widgetId, name); refresh() }
            }.setNegativeButton("Отмена", null).show()
    }

    private fun showCreateWidgetDialog() {
        val input = themedInput("Например: Семья, Работа, Котики")
        val box = android.widget.LinearLayout(this).apply {
            orientation = android.widget.LinearLayout.VERTICAL; setPadding(dp(22), dp(10), dp(22), dp(4)); addView(input)
        }
        android.app.AlertDialog.Builder(this).setTitle("Новый виджет").setView(box)
            .setPositiveButton("Далее: размер") { _, _ ->
                val name = input.text.toString().trim()
                if (name.isEmpty()) toast("Введите название виджета") else chooseWidgetSize(name)
            }.setNegativeButton("Отмена", null).show()
    }

    private fun showWidgetAlbumActions(widgetId: Int) {
        data class Action(val label: String, val run: () -> Unit)
        val auto = PinnedPhotoWidgetBase.autoEnabled(this, widgetId)
        val actions = mutableListOf<Action>()
        actions.add(Action("Переименовать виджет") { showRenameWidgetDialog(widgetId) })
        actions.add(Action("Слияние в другой виджет…") {
            val others = PinnedPhotoWidgetBase.installedWidgetIds(this).filterNot { it == widgetId }
            if (others.isEmpty()) toast("Нет другого виджета") else {
                android.app.AlertDialog.Builder(this).setTitle("Слить «${PinnedPhotoWidgetBase.widgetName(this, widgetId)}» в…")
                    .setItems(others.map { PinnedPhotoWidgetBase.widgetName(this, it) }.toTypedArray()) { _, which ->
                        val ids = PinnedPhotoWidgetBase.getWidgetPhotoIds(this, widgetId)
                        val added = PinnedPhotoWidgetBase.addCopiesToWidgets(this, ids, listOf(others[which]))
                        toast("Добавлено ссылок: $added. Исходный виджет не очищен"); refresh()
                    }.setNegativeButton("Отмена", null).show()
            }
        })
        actions.add(Action("Очистить альбом виджета…") {
            android.app.AlertDialog.Builder(this).setTitle("Очистить «${PinnedPhotoWidgetBase.widgetName(this, widgetId)}»?")
                .setMessage("Сам виджет Android удалить из приложения нельзя — это делает лаунчер долгим нажатием по виджету. Здесь можно только убрать все фото, виджет останется пустым. Оригиналы фото не удаляются.")
                .setPositiveButton("Очистить") { _, _ ->
                    PinnedPhotoWidgetBase.clearWidget(this, widgetId)
                    if (selectedAlbum == WIDGET_PREFIX + widgetId) selectedAlbum = ALL_ALBUMS
                    toast("Альбом виджета очищен"); refresh()
                }.setNegativeButton("Отмена", null).show()
        })
        actions.add(Action(if (auto) "Отключить автопереключение" else "Включить автопереключение") {
            PinnedPhotoWidgetBase.setAutoEnabled(this, widgetId, !auto); PinnedPhotoWidgetBase.updateAll(this); toast("Автопереключение: ${if (!auto) "включено" else "выключено"}"); refresh()
        })
        actions.add(Action("Время автопереключения: ${PinnedPhotoWidgetBase.intervalMinutes(this, widgetId)} мин") {
            val labels = arrayOf("30 минут", "1 час", "3 часа", "6 часов", "12 часов")
            val values = listOf(30, 60, 180, 360, 720)
            android.app.AlertDialog.Builder(this).setTitle("Автопереключение: ${PinnedPhotoWidgetBase.widgetName(this, widgetId)}")
                .setItems(labels) { _, which -> PinnedPhotoWidgetBase.setIntervalMinutes(this, widgetId, values[which]); toast("Интервал: ${labels[which]}. Android может округлять обновления."); refresh() }
                .setNegativeButton("Отмена", null).show()
        })
        android.app.AlertDialog.Builder(this).setTitle(PinnedPhotoWidgetBase.widgetName(this, widgetId))
            .setItems(actions.map { it.label }.toTypedArray()) { _, which -> actions[which].run() }
            .setNegativeButton("Отмена", null).show()
    }

    private fun albumTile(album: String, albumPhotos: List<Photo>): View {
        val security = PhotoStore.securityFor(this, album)
        val isLocked = security.locked && album !in unlockedAlbums
        val tile = android.widget.FrameLayout(this).apply {
            setBackgroundResource(if (album == selectedAlbum) R.drawable.btn_primary else R.drawable.card_bg)
            clipToOutline = true
            setOnClickListener {
                if (isLocked) {
                    showUnlockDialog(album) { selectedAlbum = album; refresh() }
                } else if (album == PhotoStore.MISC_ALBUM && selectedAlbum == album) {
                    // Уже в «Разное»: повторные нажатия ничего не меняют.
                } else if (selectedAlbum == album) {
                    selectedAlbum = ALL_ALBUMS; unlockedAlbums.remove(album); refresh()
                } else if (isLocked) {
                    showUnlockDialog(album) { selectedAlbum = album; refresh() }
                } else { selectedAlbum = album; refresh() }
            }
            setOnLongClickListener {
                if (isLocked) showUnlockDialog(album) { showAlbumActions(album) }
                else showAlbumActions(album)
                true
            }
        }
        val cover = ImageView(this).apply {
            scaleType = ImageView.ScaleType.CENTER_CROP
            setImageResource(R.drawable.widget_placeholder)
        }
        tile.addView(cover, android.widget.FrameLayout.LayoutParams(
            android.widget.FrameLayout.LayoutParams.MATCH_PARENT, dp(72)))
        val newest = if (isLocked) null else albumPhotos.maxByOrNull { it.createdAt }
        if (newest != null) {
            cover.tag = album
            io.execute {
                val bmp = PhotoStore.decodeBitmap(this, newest, 360)
                cover.post { if (cover.tag == album && bmp != null) cover.setImageBitmap(bmp) }
            }
        }
        val label = TextView(this).apply {
            text = if (isLocked) "🔒 $album" else "$album · ${albumPhotos.size}"
            textSize = 12f; gravity = android.view.Gravity.CENTER
            setTextColor(if (album == selectedAlbum) 0xFFFFFFFF.toInt() else UiTheme.color(this@MainActivity, R.attr.appText))
            setPadding(dp(4), dp(5), dp(4), dp(5))
        }
        val labelParams = android.widget.FrameLayout.LayoutParams(
            android.widget.FrameLayout.LayoutParams.MATCH_PARENT,
            android.widget.FrameLayout.LayoutParams.WRAP_CONTENT,
            android.view.Gravity.BOTTOM)
        tile.addView(label, labelParams)
        tile.layoutParams = android.widget.LinearLayout.LayoutParams(dp(104), dp(104)).apply { marginEnd = dp(10) }
        return tile
    }

    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()
    private fun selectedWidgetId(): Int = selectedAlbum.removePrefix(WIDGET_PREFIX).toIntOrNull() ?: 0

    private fun chooseWidgetsForPhotos(sourceIds: List<String>) {
        if (sourceIds.isEmpty()) { toast("Сначала выберите фото"); return }
        val widgetIds = PinnedPhotoWidgetBase.installedWidgetIds(this)
        if (widgetIds.isEmpty()) { toast("Сначала добавьте виджет на рабочий стол — пока назначать некуда"); return }
        if (widgetIds.size == 1) {
            val added = PinnedPhotoWidgetBase.addCopiesToWidgets(this, sourceIds, widgetIds)
            selectedIds.clear(); toast(if (added > 0) "Добавлено в виджет: $added" else "Эти фото уже есть в виджете"); refresh(); return
        }
        val labels = widgetIds.map { widgetId ->
            val already = sourceIds.all { it in PinnedPhotoWidgetBase.getWidgetPhotoIds(this, widgetId) }
            if (already) "${PinnedPhotoWidgetBase.widgetName(this, widgetId)} · уже там ✓" else PinnedPhotoWidgetBase.widgetName(this, widgetId)
        }.toTypedArray()
        val checked = BooleanArray(widgetIds.size)
        android.app.AlertDialog.Builder(this)
            .setTitle("Добавить копии в виджеты")
            .setMultiChoiceItems(labels, checked) { _, which, isChecked -> checked[which] = isChecked }
            .setPositiveButton("Добавить") { _, _ ->
                val chosen = widgetIds.filterIndexed { index, _ -> checked[index] }
                if (chosen.isEmpty()) toast("Ни один виджет не выбран") else {
                    val added = PinnedPhotoWidgetBase.addCopiesToWidgets(this, sourceIds, chosen)
                    selectedIds.clear(); toast("Добавлено ссылок: $added"); refresh()
                }
            }
            .setNeutralButton("Во все") { _, _ ->
                val added = PinnedPhotoWidgetBase.addCopiesToWidgets(this, sourceIds, widgetIds)
                selectedIds.clear(); toast("Добавлено ссылок: $added"); refresh()
            }
            .setNegativeButton("Отмена", null).show()
    }

    private fun shareSelected() {
        val chosen = photos.filter { it.id in selectedIds }
        if (chosen.isEmpty()) return
        io.execute {
            try {
                val uris = arrayListOf<Uri>()
                val dir = File(cacheDir, "shared").apply { mkdirs() }
                chosen.forEachIndexed { index, photo ->
                    val plain = PhotoStore.plainBytes(this, photo) ?: return@forEachIndexed
                    val ext = photo.file.substringAfterLast('.', "jpg")
                    val out = File(dir, "share_${photo.id}_$index.$ext"); out.writeBytes(plain)
                    uris.add(FileProvider.getUriForFile(this, packageName + ".fileprovider", out))
                }
                runOnUiThread {
                    if (uris.isEmpty()) { toast("Не удалось подготовить фото"); return@runOnUiThread }
                    val intent = if (uris.size == 1) Intent(Intent.ACTION_SEND).apply {
                        type = chosen.first().mime; putExtra(Intent.EXTRA_STREAM, uris.first())
                    } else Intent(Intent.ACTION_SEND_MULTIPLE).apply {
                        type = "*/*"; putParcelableArrayListExtra(Intent.EXTRA_STREAM, uris)
                    }
                    intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    startActivity(Intent.createChooser(intent, "Поделиться"))
                }
            } catch (e: Exception) { runOnUiThread { toast("Ошибка: ${e.message}") } }
        }
    }

    private fun confirmDeleteSelected() {
        if (selectedIds.isEmpty()) return
        val count = selectedIds.size
        android.app.AlertDialog.Builder(this)
            .setTitle("Удалить выбранные копии?")
            .setMessage("Будет удалено копий: $count. Копии того же фото в других альбомах и виджетах не тронем. Оригиналы в галерее не трогаем.")
            .setPositiveButton("Удалить") { _, _ ->
                photos.filter { it.id in selectedIds }.forEach { PhotoStore.delete(this, it) }
                selectedIds.clear(); toast("Удалено копий: $count"); refresh()
            }
            .setNegativeButton("Отмена", null).show()
    }


    // ---------- Защита альбомов и действия по долгому нажатию ----------

    private fun themedInput(hintText: String, numericPin: Boolean = false): android.widget.EditText {
        return android.widget.EditText(this).apply {
            hint = hintText; setSingleLine(true); setBackgroundResource(R.drawable.input_bg)
            setTextColor(UiTheme.color(this@MainActivity, R.attr.appText))
            setHintTextColor(UiTheme.color(this@MainActivity, R.attr.appMuted))
            if (numericPin) {
                inputType = android.text.InputType.TYPE_CLASS_NUMBER or android.text.InputType.TYPE_NUMBER_VARIATION_PASSWORD
                filters = arrayOf(android.text.InputFilter.LengthFilter(4))
            }
        }
    }

    private fun showUnlockDialog(album: String, onSuccess: () -> Unit) {
        val security = PhotoStore.securityFor(this, album)
        val input = themedInput("4-значный пароль", numericPin = true)
        val box = android.widget.LinearLayout(this).apply {
            orientation = android.widget.LinearLayout.VERTICAL
            setPadding(dp(22), dp(10), dp(22), dp(4)); addView(input)
        }
        val builder = android.app.AlertDialog.Builder(this)
            .setTitle("🔒 $album")
            .setView(box)
            .setNegativeButton("Отмена", null)
        if (security.pinHash.isNotEmpty()) {
            builder.setPositiveButton("Открыть") { _, _ ->
                val pin = input.text.toString()
                if (PhotoStore.verifyAlbumPin(this, album, pin)) {
                    unlockedAlbums.add(album); onSuccess()
                } else toast("Неверный пароль")
            }
        }
        // Отпечаток предлагаем СРАЗУ поверх окна пароля. Успех закрывает оба окна
        // и открывает альбом на эту сессию (пока приложение не закрыто / альбом не закрыт вручную).
        val dialog = builder.create(); dialog.show()
        if (biometricAvailable()) {
            dialog.setOnShowListener {
                authenticateBiometric(album) { dialog.dismiss(); onSuccess() }
            }
        }
    }

    private fun biometricAvailable(): Boolean {
        val manager = BiometricManager.from(this)
        val auth = BiometricManager.Authenticators.BIOMETRIC_STRONG or BiometricManager.Authenticators.BIOMETRIC_WEAK
        return manager.canAuthenticate(auth) == BiometricManager.BIOMETRIC_SUCCESS
    }

    private fun authenticateBiometric(album: String, onSuccess: () -> Unit) {
        val manager = BiometricManager.from(this)
        val authenticators = BiometricManager.Authenticators.BIOMETRIC_STRONG or BiometricManager.Authenticators.BIOMETRIC_WEAK
        if (manager.canAuthenticate(authenticators) != BiometricManager.BIOMETRIC_SUCCESS) {
            toast("Отпечаток недоступен на этом устройстве"); return
        }
        val prompt = BiometricPrompt(this, ContextCompat.getMainExecutor(this), object : BiometricPrompt.AuthenticationCallback() {
            override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
                unlockedAlbums.add(album); onSuccess()
            }
            override fun onAuthenticationError(errorCode: Int, errString: CharSequence) {
                if (errorCode != BiometricPrompt.ERROR_USER_CANCELED && errorCode != BiometricPrompt.ERROR_NEGATIVE_BUTTON) {
                    toast("Отпечаток не подтверждён: $errString")
                }
            }
        })
        val info = BiometricPrompt.PromptInfo.Builder()
            .setTitle("Открыть альбом")
            .setSubtitle(album)
            .setNegativeButtonText("Отмена")
            .build()
        prompt.authenticate(info)
    }

    private fun showAlbumActions(album: String) {
        val security = PhotoStore.securityFor(this, album)
        data class Action(val label: String, val run: () -> Unit)
        val actions = mutableListOf<Action>()
        if (album != PhotoStore.MISC_ALBUM) {
            actions.add(Action("Переименовать альбом") { showRenameAlbumDialog(album) })
        }
        actions.add(Action("Слияние в другой альбом…") { chooseMergeDestination(album) })
        if (album != PhotoStore.MISC_ALBUM) {
            actions.add(Action("Удалить альбом и его фото…") { confirmDeleteAlbum(album) })
        } else {
            actions.add(Action("Альбом «Разное» удалить нельзя") { toast("«Разное» — постоянный альбом приложения") })
        }
        if (security.pinHash.isEmpty()) {
            actions.add(Action("Установить 4-значный пароль") { showSetPinDialog(album) })
        } else {
            actions.add(Action("Изменить пароль") { showSetPinDialog(album) })
            actions.add(Action("Снять пароль") {
                PhotoStore.clearAlbumPin(this, album)
                if (!PhotoStore.securityFor(this, album).locked) unlockedAlbums.remove(album)
                toast("Пароль снят"); refresh()
            })
        }
        if (album in unlockedAlbums) actions.add(Action("Закрыть альбом сейчас") {
            unlockedAlbums.remove(album); if (selectedAlbum == album) selectedAlbum = ALL_ALBUMS; refresh()
        })
        android.app.AlertDialog.Builder(this)
            .setTitle(album)
            .setItems(actions.map { it.label }.toTypedArray()) { _, which -> actions[which].run() }
            .setNegativeButton("Отмена", null)
            .show()
    }

    private fun showRenameAlbumDialog(album: String) {
        val input = themedInput("Новое название альбома").apply { setText(album); setSelection(text.length) }
        val box = android.widget.LinearLayout(this).apply {
            orientation = android.widget.LinearLayout.VERTICAL; setPadding(dp(22), dp(10), dp(22), dp(4)); addView(input)
        }
        android.app.AlertDialog.Builder(this).setTitle("Переименовать альбом").setView(box)
            .setPositiveButton("Сохранить") { _, _ ->
                try {
                    val renamed = PhotoStore.renameAlbum(this, album, input.text.toString())
                    if (selectedAlbum == album) selectedAlbum = renamed
                    toast("Альбом переименован в «$renamed»"); refresh()
                } catch (e: Exception) { toast(e.message ?: "Не удалось переименовать") }
            }
            .setNegativeButton("Отмена", null).show()
    }

    private fun showSetPinDialog(album: String) {
        val first = themedInput("Новый пароль: 4 цифры", numericPin = true)
        val second = themedInput("Повторите пароль", numericPin = true)
        val box = android.widget.LinearLayout(this).apply {
            orientation = android.widget.LinearLayout.VERTICAL
            setPadding(dp(22), dp(10), dp(22), dp(4)); addView(first); addView(second)
        }
        android.app.AlertDialog.Builder(this)
            .setTitle("Пароль альбома")
            .setView(box)
            .setPositiveButton("Сохранить") { _, _ ->
                val a = first.text.toString(); val b = second.text.toString()
                when {
                    !a.matches(Regex("\\d{4}")) -> toast("Пароль должен состоять ровно из 4 цифр")
                    a != b -> toast("Пароли не совпадают")
                    else -> {
                        PhotoStore.setAlbumPin(this, album, a)
                        unlockedAlbums.add(album)
                        toast("Пароль установлен. Открыть можно паролем или отпечатком"); refresh()
                    }
                }
            }
            .setNegativeButton("Отмена", null).show()
    }

    private fun chooseMergeDestination(source: String) {
        val destinations = PhotoStore.albums(this).filterNot { it == source }
        if (destinations.isEmpty()) { toast("Нет другого альбома для слияния"); return }
        android.app.AlertDialog.Builder(this)
            .setTitle("Слить «$source» в…")
            .setItems(destinations.toTypedArray()) { _, which ->
                val moved = PhotoStore.mergeAlbums(this, source, destinations[which])
                toast("Добавлено в «${destinations[which]}»: $moved фото. В «$source» всё осталось")
                if (selectedAlbum == source) selectedAlbum = destinations[which]
                refresh()
            }
            .setNegativeButton("Отмена", null).show()
    }

    private fun confirmDeleteAlbum(album: String) {
        val count = photos.count { album in it.albums }
        android.app.AlertDialog.Builder(this)
            .setTitle("Удалить альбом?")
            .setMessage("Альбом «$album» и все его фотографии ($count шт.) будут удалены из приложения. Оригиналы в галерее телефона не тронем.")
            .setPositiveButton("Удалить всё") { _, _ ->
                val removed = PhotoStore.deleteAlbumWithPhotos(this, album)
                unlockedAlbums.remove(album)
                if (selectedAlbum == album) selectedAlbum = ALL_ALBUMS
                toast("Удалено фото: $removed"); refresh()
            }
            .setNegativeButton("Отмена", null).show()
    }


    private fun showMenu(anchor: View) {
        // Оставлены только редкие служебные действия: бэкап и иконка.
        // Добавление фото/виджета, альбомы и тема живут своими кнопками на экране.
        val popupContext = android.view.ContextThemeWrapper(this, if (UiTheme.isDark(this)) R.style.PopupOverlayDark else R.style.PopupOverlayLight)
        val menu = PopupMenu(popupContext, anchor)
        menu.menu.add(0, 1, 0, "Бэкап: сохранить JSON")
        menu.menu.add(0, 2, 0, "Восстановить из JSON")
        menu.menu.add(0, 3, 0, "Иконка: обычная 📌")
        menu.menu.add(0, 4, 0, "Иконка: огненная 🔥")
        menu.menu.add(0, 5, 0, "Иконка: сонная 😴")
        menu.menu.add(0, 6, 0, "Иконка: форменная 🖼")
        menu.menu.add(0, 7, 0, if (UiTheme.isDark(this)) "Тема: тёмная 🌙 — сменить на светлую" else "Тема: светлая ☀️ — сменить на тёмную")
        menu.setOnMenuItemClickListener { item ->
            when (item.itemId) {
                1 -> startActivityForResult(Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
                    addCategory(Intent.CATEGORY_OPENABLE); type = "application/json"
                    putExtra(Intent.EXTRA_TITLE, "pinphotos-backup.json")
                }, EXPORT_JSON)
                2 -> startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                    addCategory(Intent.CATEGORY_OPENABLE); type = "*/*"
                }, IMPORT_JSON)
                3 -> IconSwitcher.setIcon(this, IconSwitcher.NORMAL)
                4 -> IconSwitcher.setIcon(this, IconSwitcher.FIRE)
                5 -> IconSwitcher.setIcon(this, IconSwitcher.SLEEPY)
                6 -> IconSwitcher.setIcon(this, IconSwitcher.SHAPED)
                7 -> { menu.dismiss(); UiTheme.toggle(this) }
            }
            true
        }
        menu.show()
    }

    private fun importPressed() {
        if (selectedAlbum.startsWith(WIDGET_PREFIX)) {
            pendingImportWidget = selectedWidgetId(); pendingImportAlbum = ""
            pickPhotos()
            return
        }
        // «Разное» теперь тоже конкретный альбом: внутри любого открытого альбома добавляем сразу в него.
        if (PhotoStore.securityFor(this, selectedAlbum).locked && selectedAlbum !in unlockedAlbums) {
            showUnlockDialog(selectedAlbum) { pendingImportAlbum = selectedAlbum; pickPhotos() }
        } else {
            pendingImportAlbum = selectedAlbum
            pickPhotos()
        }
    }

    @Deprecated("системная кнопка/жест назад")
    override fun onBackPressed() {
        when {
            selectedIds.isNotEmpty() -> { selectedIds.clear(); refresh() }
            selectedAlbum != ALL_ALBUMS -> {
                val wasWidget = selectedAlbum.startsWith(WIDGET_PREFIX)
                selectedAlbum = ALL_ALBUMS
                if (!wasWidget) unlockedAlbums.clear()
                refresh()
            }
            else -> finish()
        }
    }

    private fun showCreateAlbumDialog(onCreated: (String) -> Unit) {
        val input = android.widget.EditText(this).apply {
            hint = "Название альбома"; setSingleLine(true); setBackgroundResource(R.drawable.input_bg)
            setTextColor(UiTheme.color(this@MainActivity, R.attr.appText)); setHintTextColor(UiTheme.color(this@MainActivity, R.attr.appMuted))
        }
        val box = android.widget.LinearLayout(this).apply {
            orientation = android.widget.LinearLayout.VERTICAL; setPadding(dp(22), dp(10), dp(22), dp(4)); addView(input)
        }
        android.app.AlertDialog.Builder(this)
            .setTitle("Новый альбом").setView(box)
            .setPositiveButton("Создать") { _, _ ->
                try { onCreated(PhotoStore.createAlbum(this, input.text.toString())); toast("Альбом создан") }
                catch (e: Exception) { toast("Введите название альбома") }
            }
            .setNegativeButton("Отмена", null).show()
    }

    private fun chooseImportAlbum() {
        val albums = PhotoStore.albums(this) // первый — всегда «Разное»
        val labels = albums.toTypedArray() + "＋ Новый альбом"
        android.app.AlertDialog.Builder(this)
            .setTitle("Добавить фото в альбом")
            .setItems(labels) { _, which ->
                if (which == albums.size) {
                    showCreateAlbumDialog { album -> pendingImportAlbum = album; pickPhotos() }
                } else { pendingImportAlbum = albums[which]; pickPhotos() }
            }
            .show()
    }

    private fun chooseMoveAlbum() {
        if (selectedIds.isEmpty()) return
        val albums = PhotoStore.albums(this)
        val labels = albums.toTypedArray() + "＋ Новый альбом"
        android.app.AlertDialog.Builder(this)
            .setTitle("Переместить ${selectedIds.size} фото")
            .setItems(labels) { _, which ->
                if (which == albums.size) {
                    showCreateAlbumDialog { album -> moveSelectedTo(album) }
                } else moveSelectedTo(albums[which])
            }
            .setNegativeButton("Отмена", null)
            .show()
    }

    private fun moveSelectedTo(album: String) {
        photos.filter { it.id in selectedIds }.forEach { p -> p.albums = mutableListOf(album); PhotoStore.update(this, p) }
        val count = selectedIds.size
        selectedIds.clear(); selectedAlbum = album
        toast("Перемещено: $count"); refresh()
    }

    private fun pickPhotos() {
        val intent = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
            addCategory(Intent.CATEGORY_OPENABLE); type = "*/*"
            putExtra(Intent.EXTRA_MIME_TYPES, arrayOf("image/*", "video/*"))
            putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        startActivityForResult(intent, PICK_PHOTOS)
    }

    private fun chooseWidgetSize(widgetName: String) {
        val labels = arrayOf("2 × 2", "3 × 2", "4 × 2", "4 × 3")
        android.app.AlertDialog.Builder(this)
            .setTitle("Размер виджета «$widgetName»")
            .setItems(labels) { _, which ->
                // ID виджета появится только после размещения на рабочем столе; имя ждёт в очереди.
                PinnedPhotoWidgetBase.queuePendingWidgetName(this, widgetName)
                requestPin(PinnedPhotoWidgetBase.PROVIDERS[which])
            }
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
                        val mime = contentResolver.getType(uri) ?: "image/jpeg"
                        if (!mime.startsWith("image/") && !mime.startsWith("video/")) continue
                        val imported = PhotoStore.importBytes(this, bytes, mime, displayName(uri))
                        val hash = PhotoStore.sha256(bytes)
                        // ВАЖНО: imported уже сохранён в PhotoStore, поэтому ищем дубликат среди ДРУГИХ записей.
                        val duplicate = PhotoStore.list(this).firstOrNull { other ->
                            other.id != imported.id && other.widgetId == 0 && other.hash == hash && when {
                                pendingImportWidget > 0 -> true
                                pendingImportAlbum.isNotBlank() -> pendingImportAlbum in other.albums
                                else -> other.albums.isEmpty()
                            }
                        }
                        if (duplicate != null && pendingImportWidget == 0) { PhotoStore.delete(this, imported); continue }
                        if (pendingImportWidget > 0) {
                            imported.albums = mutableListOf(); PhotoStore.update(this, imported)
                            PinnedPhotoWidgetBase.addCopiesToWidgets(this, listOf(imported.id), listOf(pendingImportWidget))
                        } else {
                            imported.albums = if (pendingImportAlbum.isBlank()) mutableListOf() else mutableListOf(pendingImportAlbum); PhotoStore.update(this, imported)
                        }
                        saved++
                    } catch (e: Exception) { /* одно битое фото не должно валить остальные */ }
                }
                runOnUiThread { toast("Добавлено: $saved"); pendingImportWidget = 0; refresh() }
            }
            EXPORT_JSON -> io.execute {
                try {
                    val arr = org.json.JSONArray()
                    for (p in photos) {
                        val bytes = PhotoStore.plainBytes(this, p) ?: continue
                        arr.put(JSONObject()
                            .put("name", p.name).put("album", p.album).put("albums", org.json.JSONArray(p.albums)).put("tags", org.json.JSONArray(p.tags))
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
                        p.albums = mutableListOf<String>().apply {
                            o.optJSONArray("albums")?.let { a -> for (j in 0 until a.length()) a.optString(j).takeIf { it.isNotBlank() }?.let { add(it) } }
                            if (isEmpty()) o.optString("album").takeIf { it.isNotBlank() && it != "Разное" }?.let { add(it) }
                        }; p.note = o.optString("note")
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

    companion object {
        const val PICK_PHOTOS = 2001; const val EXPORT_JSON = 2002; const val IMPORT_JSON = 2003
        const val ALL_ALBUMS = PhotoStore.MISC_ALBUM
        const val WIDGET_PREFIX = "__widget__:"
    }
}

class PhotoAdapter(
    private val items: List<Photo>,
    private val selectedIds: Set<String>,
    private val widgetPhotoIds: Set<String> = emptySet(),
    private val onClick: (Photo) -> Unit,
    private val onLongClick: (Photo) -> Unit
) : RecyclerView.Adapter<PhotoAdapter.Holder>() {
    class Holder(view: View) : RecyclerView.ViewHolder(view) {
        val thumb: ImageView = view.findViewById(R.id.thumb)
        val badge: TextView = view.findViewById(R.id.badge)
    }

    override fun onCreateViewHolder(parent: ViewGroup, type: Int): Holder =
        Holder(LayoutInflater.from(parent.context).inflate(R.layout.item_photo, parent, false))

    override fun getItemCount() = items.size

    companion object {
        // Один общий executor на все адаптеры. Раньше каждый refresh создавал новый пул потоков.
        private val IO = Executors.newFixedThreadPool(2)
    }

    override fun onBindViewHolder(holder: Holder, position: Int) {
        val photo = items[position]
        val selected = photo.id in selectedIds
        holder.badge.text = if (selected) "✓" else "📌"
        holder.badge.gravity = android.view.Gravity.CENTER
        holder.badge.includeFontPadding = false
        // У глифа ✓ есть левый боковой зазор шрифта: небольшой сдвиг вправо ставит его визуально по центру круга.
        holder.badge.translationX = if (selected) 2f else 0f
        holder.badge.setBackgroundResource(if (selected) R.drawable.selection_badge else R.drawable.badge_bg)
        holder.badge.setTextColor(if (selected) 0xFFFFFFFF.toInt() else 0xFF111827.toInt())
        holder.badge.visibility = if (selected || photo.pinned || photo.widgetId > 0 || photo.id in widgetPhotoIds) View.VISIBLE else View.GONE
        if (!selected && (photo.widgetId > 0 || photo.id in widgetPhotoIds)) holder.badge.text = "🧩"
        holder.thumb.alpha = if (selected) 0.78f else 1f
        holder.itemView.setBackgroundResource(if (selected) R.drawable.selection_frame else R.drawable.card_bg)
        holder.thumb.setImageResource(R.drawable.widget_placeholder)
        holder.thumb.tag = photo.id
        val path = photo.fileIn(PhotoStore.dir(holder.thumb.context)).absolutePath
        IO.execute {
            val bmp = PhotoStore.decodeBitmap(holder.thumb.context, photo, 360)
            holder.thumb.post { if (holder.thumb.tag == photo.id && bmp != null) holder.thumb.setImageBitmap(bmp) }
        }
        holder.itemView.setOnClickListener { onClick(photo) }
        holder.itemView.setOnLongClickListener { onLongClick(photo); true }
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
