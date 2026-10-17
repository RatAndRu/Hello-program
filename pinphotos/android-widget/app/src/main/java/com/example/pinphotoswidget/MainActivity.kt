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
    private lateinit var widgetStatus: TextView
    private lateinit var countText: TextView
    private var photos: MutableList<Photo> = mutableListOf()
    private var selectedAlbum: String = ALL_ALBUMS
    private var pendingImportAlbum: String = ""
    private var pendingImportWidget: Int = 0
    private var searchQuery: String = ""
    private var sortMode: Int = 0
    private val selectedIds = linkedSetOf<String>()
    private val unlockedAlbums = mutableSetOf<String>()
    private val io = Executors.newFixedThreadPool(3)

    override fun onCreate(savedInstanceState: Bundle?) {
        UiTheme.apply(this)
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        grid = findViewById(R.id.grid)
        emptyView = findViewById(R.id.emptyView)
        widgetStatus = findViewById(R.id.widgetStatus)
        countText = findViewById(R.id.countText)
        grid.layoutManager = GridLayoutManager(this, 3)
        findViewById<Button>(R.id.importBtn).setOnClickListener { importPressed() }
        findViewById<Button>(R.id.emptyImportBtn).setOnClickListener { importPressed() }
        findViewById<Button>(R.id.addWidgetBtn).setOnClickListener { chooseWidgetSize() }
        findViewById<View>(R.id.menuBtn).setOnClickListener { showMenu(it) }
        findViewById<View>(R.id.exitBtn).setOnClickListener { finishAndRemoveTask() }
        val themeBtn = findViewById<TextView>(R.id.themeBtn)
        themeBtn.text = if (UiTheme.isDark(this)) "☀️" else "🌙"
        themeBtn.setOnClickListener { UiTheme.toggle(this) }
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
        val sortLabels = listOf("Сначала новые", "Сначала старые", "По алфавиту А–Я", "По алфавиту Я–А")
        val sortSpinner = findViewById<android.widget.Spinner>(R.id.sortSpinner)
        sortSpinner.adapter = object : android.widget.ArrayAdapter<String>(this, R.layout.spinner_item, sortLabels) {
            override fun getDropDownView(position: Int, convertView: View?, parent: ViewGroup): View {
                val view = super.getDropDownView(position, convertView, parent) as TextView
                view.setBackgroundColor(UiTheme.color(this@MainActivity, R.attr.appSurface)); view.setTextColor(UiTheme.color(this@MainActivity, R.attr.appText)); return view
            }
        }.apply { setDropDownViewResource(R.layout.spinner_dropdown_item) }
        sortSpinner.setPopupBackgroundResource(if (UiTheme.isDark(this)) R.drawable.dialog_bg_dark else R.drawable.dialog_bg_light)
        sortSpinner.onItemSelectedListener = object : android.widget.AdapterView.OnItemSelectedListener {
            override fun onItemSelected(parent: android.widget.AdapterView<*>?, view: View?, position: Int, id: Long) { if (sortMode != position) { sortMode = position; refresh() } }
            override fun onNothingSelected(parent: android.widget.AdapterView<*>?) {}
        }
    }

    override fun onResume() { super.onResume(); refresh() }

    private fun refresh() {
        photos = PhotoStore.list(this)
        val lockedNames = PhotoStore.lockedAlbumNames(this)
        val ordinaryPhotos = photos.filter { it.widgetId == 0 }
        val visiblePhotos = ordinaryPhotos.filter { photo -> photo.albums.none { it in lockedNames } }
        val widgetPhotosCount = photos.count { it.widgetId > 0 }
        val pinnedCount = if (widgetPhotosCount > 0) widgetPhotosCount else visiblePhotos.count { it.pinned }
        countText.text = if (visiblePhotos.isEmpty()) "" else "${visiblePhotos.size}"
        widgetStatus.text = when {
            PinnedPhotoWidgetBase.installedWidgetIds(this).isEmpty() -> "Виджет не добавлен на рабочий стол"
            pinnedCount == 0 -> "В виджетах пусто — выберите фото и нажмите «В виджет»"
            pinnedCount == 1 -> "В виджетах: 1 отдельная копия фото"
            else -> "В виджетах: $pinnedCount отдельных копий · каждый виджет свой"
        }
        renderAlbums(); renderWidgetAlbums()
        val baseDisplayed = when {
            selectedAlbum.startsWith(WIDGET_PREFIX) -> photos.filter { it.widgetId == selectedWidgetId() }
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
        grid.adapter = PhotoAdapter(displayed, selectedIds,
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
        PinnedPhotoWidgetBase.updateAll(this)
    }

    private fun toggleSelected(photo: Photo) {
        if (!selectedIds.add(photo.id)) selectedIds.remove(photo.id)
        refresh()
    }

    private fun renderAlbums() {
        findViewById<TextView>(R.id.currentAlbumText).text = when {
            selectedAlbum == ALL_ALBUMS -> "Все фото"
            selectedAlbum.startsWith(WIDGET_PREFIX) -> "Виджет №${selectedWidgetId()}"
            else -> selectedAlbum
        }
        val row = findViewById<android.widget.LinearLayout>(R.id.albumsTiles)
        row.removeAllViews()
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

    private fun albumTile(album: String, albumPhotos: List<Photo>): View {
        val security = PhotoStore.securityFor(this, album)
        val isLocked = security.locked && album !in unlockedAlbums
        val tile = android.widget.FrameLayout(this).apply {
            setBackgroundResource(if (album == selectedAlbum) R.drawable.btn_primary else R.drawable.card_bg)
            clipToOutline = true
            setOnClickListener {
                if (selectedAlbum == album) {
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

    private fun renderWidgetAlbums() {
        val section = findViewById<View>(R.id.widgetAlbumsSection)
        val row = findViewById<android.widget.LinearLayout>(R.id.widgetAlbumsTiles)
        val widgetIds = PinnedPhotoWidgetBase.installedWidgetIds(this)
        section.visibility = if (widgetIds.isEmpty()) View.GONE else View.VISIBLE
        row.removeAllViews()
        for (widgetId in widgetIds) {
            val copies = photos.filter { it.widgetId == widgetId }
            val key = WIDGET_PREFIX + widgetId
            val tile = TextView(this).apply {
                text = "🧩 Виджет №$widgetId\n${copies.size} фото"; textSize = 13f; gravity = android.view.Gravity.CENTER
                setPadding(dp(8), dp(8), dp(8), dp(8))
                setTextColor(if (selectedAlbum == key) 0xFFFFFFFF.toInt() else UiTheme.color(this@MainActivity, R.attr.appText))
                setBackgroundResource(if (selectedAlbum == key) R.drawable.btn_primary else R.drawable.card_bg)
                setOnClickListener { selectedAlbum = if (selectedAlbum == key) ALL_ALBUMS else key; refresh() }
            }
            row.addView(tile, android.widget.LinearLayout.LayoutParams(dp(118), dp(76)).apply { marginEnd = dp(10) })
        }
        if (selectedAlbum.startsWith(WIDGET_PREFIX) && selectedWidgetId() !in widgetIds) selectedAlbum = ALL_ALBUMS
    }

    private fun chooseWidgetsForPhotos(sourceIds: List<String>) {
        if (sourceIds.isEmpty()) { toast("Сначала выберите фото"); return }
        val widgetIds = PinnedPhotoWidgetBase.installedWidgetIds(this)
        if (widgetIds.isEmpty()) { toast("Сначала добавьте виджет на рабочий стол — пока назначать некуда"); return }
        if (widgetIds.size == 1) {
            val added = PinnedPhotoWidgetBase.addCopiesToWidgets(this, sourceIds, widgetIds)
            selectedIds.clear(); toast(if (added > 0) "Добавлено копий в виджет: $added" else "Эти фото уже есть в виджете"); refresh(); return
        }
        val labels = widgetIds.map { "Виджет №$it" }.toTypedArray()
        val checked = BooleanArray(widgetIds.size)
        android.app.AlertDialog.Builder(this)
            .setTitle("Добавить копии в виджеты")
            .setMultiChoiceItems(labels, checked) { _, which, isChecked -> checked[which] = isChecked }
            .setPositiveButton("Добавить") { _, _ ->
                val chosen = widgetIds.filterIndexed { index, _ -> checked[index] }
                if (chosen.isEmpty()) toast("Ни один виджет не выбран") else {
                    val added = PinnedPhotoWidgetBase.addCopiesToWidgets(this, sourceIds, chosen)
                    selectedIds.clear(); toast("Добавлено копий: $added"); refresh()
                }
            }
            .setNeutralButton("Во все") { _, _ ->
                val added = PinnedPhotoWidgetBase.addCopiesToWidgets(this, sourceIds, widgetIds)
                selectedIds.clear(); toast("Добавлено копий: $added"); refresh()
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
        actions.add(Action("Слияние в другой альбом…") { chooseMergeDestination(album) })
        actions.add(Action("Удалить альбом и его фото…") { confirmDeleteAlbum(album) })
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
            }
            true
        }
        menu.show()
    }

    private fun importPressed() {
        if (selectedAlbum.startsWith(WIDGET_PREFIX)) {
            pendingImportWidget = selectedWidgetId(); pendingImportAlbum = ""
            pickPhotos()
        } else if (selectedAlbum != ALL_ALBUMS) {
            pendingImportAlbum = selectedAlbum
            pickPhotos()
        } else chooseImportAlbum()
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
        val albums = listOf("") + PhotoStore.albums(this) // "" = без альбома
        val labels = albums.map { if (it.isEmpty()) "Без альбома" else it }.toTypedArray() + "＋ Новый альбом"
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
                        val mime = contentResolver.getType(uri) ?: "image/jpeg"
                        if (!mime.startsWith("image/") && !mime.startsWith("video/")) continue
                        val imported = PhotoStore.importBytes(this, bytes, mime, displayName(uri))
                        val hash = PhotoStore.sha256(bytes)
                        val duplicate = when {
                            pendingImportWidget > 0 -> PhotoStore.findDuplicate(this, hash, null, pendingImportWidget)
                            pendingImportAlbum.isNotBlank() -> PhotoStore.findDuplicate(this, hash, pendingImportAlbum)
                            else -> PhotoStore.list(this).firstOrNull { it.widgetId == 0 && it.albums.isEmpty() && it.hash == hash }
                        }
                        if (duplicate != null) { PhotoStore.delete(this, imported); continue }
                        if (pendingImportWidget > 0) {
                            PinnedPhotoWidgetBase.addCopiesToWidgets(this, listOf(imported.id), listOf(pendingImportWidget))
                            PhotoStore.delete(this, imported)
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
        const val ALL_ALBUMS = "__all__"
        const val WIDGET_PREFIX = "__widget__:"
    }
}

class PhotoAdapter(
    private val items: List<Photo>,
    private val selectedIds: Set<String>,
    private val onClick: (Photo) -> Unit,
    private val onLongClick: (Photo) -> Unit
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
        val selected = photo.id in selectedIds
        holder.badge.text = if (selected) "✓" else "📌"
        holder.badge.setBackgroundResource(if (selected) R.drawable.selection_badge else R.drawable.badge_bg)
        holder.badge.setTextColor(if (selected) 0xFFFFFFFF.toInt() else 0xFF111827.toInt())
        holder.badge.visibility = if (selected || photo.pinned || photo.widgetId > 0) View.VISIBLE else View.GONE
        if (photo.widgetId > 0 && !selected) holder.badge.text = "🧩"
        holder.thumb.alpha = if (selected) 0.78f else 1f
        holder.itemView.setBackgroundResource(if (selected) R.drawable.selection_frame else R.drawable.card_bg)
        holder.thumb.setImageResource(R.drawable.widget_placeholder)
        holder.thumb.tag = photo.id
        val path = photo.fileIn(PhotoStore.dir(holder.thumb.context)).absolutePath
        io.execute {
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
