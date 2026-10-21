package com.example.bluelink

import android.Manifest
import android.app.Activity
import android.app.Dialog
import android.bluetooth.BluetoothAdapter
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Color
import android.graphics.drawable.ColorDrawable
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.HorizontalScrollView
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.UUID

/**
 * BlueLink — универсальный пульт для Bluetooth-устройств.
 *
 * Идея: одно приложение, которое подключается к любым BLE-устройствам (наушники, очки, часы,
 * датчики), показывает их сервисы и характеристики, а через «профили» умеет пользоваться
 * возможностями конкретного устройства — например, снимать фото камерой умных очков.
 */
class MainActivity : Activity(), BleListener, GlassesCamera.Listener {

    private lateinit var ble: BleCentral
    private lateinit var profiles: ProfileStore
    private lateinit var wifi: WifiHelper
    private lateinit var camera: GlassesCamera
    private lateinit var store: PhotoStore

    private val ui = Handler(Looper.getMainLooper())
    private val prefs by lazy { getSharedPreferences("bluelink", Context.MODE_PRIVATE) }

    private lateinit var nav: LinearLayout
    private lateinit var contentSlot: LinearLayout
    private lateinit var statusBadge: TextView
    private lateinit var subtitle: TextView
    private lateinit var mainScroll: ScrollView
    private var lastBuiltTab = ""
    private var lastThrottledRebuild = 0L
    private var batteryAttempted = false

    private var tab = TAB_SCAN
    private val scanItems = ArrayList<ScanItem>()
    private var scanning = false
    private var scanMessage: String? = null

    private var connState = ConnState.IDLE
    private var connName = ""
    private var connAddress = ""
    private var gattServices: List<GattServiceInfo> = emptyList()
    private var activeProfile: DeviceProfile? = null
    private var batteryPercent: Int? = null

    private var captureStatus = "Готов к съёмке"
    private var captureDetail = ""
    private var lastPhoto: File? = null
    private var lastPhotoBitmap: Bitmap? = null

    private val logs = ArrayList<String>()
    private val subscribed = HashSet<String>()
    private var consoleService: UUID? = null
    private var consoleChar: UUID? = null
    private var consoleTextMode = false
    private var consoleDraft = ""
    private var consoleLogView: TextView? = null
    private var consoleScroll: ScrollView? = null

    private var pendingAfterPermission: (() -> Unit)? = null
    private var pendingAfterEnable: (() -> Unit)? = null
    private var pendingGalleryExport: File? = null

    // ---------- Жизненный цикл ----------

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        ble = BleCentral(this)
        ble.listener = this
        profiles = ProfileStore(this)
        profiles.load()
        wifi = WifiHelper(this)
        camera = GlassesCamera(this, ble, wifi)
        camera.listener = this
        store = PhotoStore(this)
        activeProfile = profiles.byId(prefs.getString("active_profile", null))

        buildRoot()
        rebuild()
        addLog("BlueLink запущен")

        if (!ble.isSupported()) {
            addLog("Bluetooth не поддерживается этим устройством")
        } else if (!ble.hasPermissions()) {
            requestBlePermissions()
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        try {
            ble.stopScan()
            wifi.release()
        } catch (ignored: Exception) {
        }
    }

    override fun onResume() {
        super.onResume()
        updateHeader()
    }

    // ---------- Каркас экрана ----------

    private fun buildRoot() {
        val root = LinearLayout(this)
        root.orientation = LinearLayout.VERTICAL
        root.setBackgroundColor(Pal.BG)

        val header = column()
        header.setPadding(dp(18), dp(16), dp(18), dp(8))
        val top = row()
        val titleBox = column()
        titleBox.addView(txt("BlueLink", 23, Pal.TEXT, bold = true))
        subtitle = txt("Bluetooth-пульт для любых устройств", 11, Pal.MUTED)
        titleBox.addView(subtitle)
        top.addView(titleBox, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        statusBadge = txt("", 11, Pal.MUTED, bold = true)
        statusBadge.setPadding(dp(10), dp(5), dp(10), dp(5))
        top.addView(statusBadge)
        header.addView(top)
        root.addView(header)

        val navScroll = HorizontalScrollView(this)
        navScroll.isHorizontalScrollBarEnabled = false
        nav = row()
        nav.setPadding(dp(14), dp(2), dp(14), dp(8))
        navScroll.addView(nav)
        root.addView(navScroll)
        root.addView(divider())

        val scroll = ScrollView(this)
        scroll.isFillViewport = true
        mainScroll = scroll
        contentSlot = column()
        contentSlot.setPadding(dp(14), dp(12), dp(14), dp(28))
        scroll.addView(
            contentSlot,
            FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
            )
        )
        root.addView(
            scroll,
            LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f)
        )

        setContentView(root)
    }

    private fun rebuild() {
        if (isFinishing || isDestroyed) return
        // Список устройств обновляется каждые 400 мс во время скана — не сбрасываем прокрутку.
        val keepScroll = lastBuiltTab == tab
        val scrollY = if (keepScroll && ::mainScroll.isInitialized) mainScroll.scrollY else 0
        consoleLogView = null
        consoleScroll = null
        nav.removeAllViews()
        for ((id, title) in TABS) {
            nav.addView(pill(title, id == tab) {
                tab = id
                rebuild()
            })
        }
        contentSlot.removeAllViews()
        val view = when (tab) {
            TAB_SCAN -> buildScanTab()
            TAB_DEVICE -> buildDeviceTab()
            TAB_CAMERA -> buildCameraTab()
            TAB_GATT -> buildGattTab()
            TAB_PROFILES -> buildProfilesTab()
            TAB_PHOTOS -> buildPhotosTab()
            else -> buildConsoleTab()
        }
        contentSlot.addView(view)
        lastBuiltTab = tab
        updateHeader()
        if (keepScroll && ::mainScroll.isInitialized && scrollY > 0) {
            mainScroll.post { mainScroll.scrollTo(0, scrollY) }
        }
    }

    /** Перестройка экрана не чаще двух раз в секунду: иначе поток уведомлений «задушит» интерфейс. */
    private fun rebuildThrottled() {
        val now = System.currentTimeMillis()
        if (now - lastThrottledRebuild < 500) return
        lastThrottledRebuild = now
        rebuild()
    }

    private fun updateHeader() {
        if (!::subtitle.isInitialized) return
        val connected = connState == ConnState.CONNECTED
        statusBadge.text = when {
            connected -> "● подключено"
            connState == ConnState.CONNECTING -> "● соединение…"
            !ble.isSupported() -> "нет Bluetooth"
            !ble.isEnabled() -> "Bluetooth выкл."
            else -> "○ не подключено"
        }
        statusBadge.setTextColor(
            when {
                connected -> Pal.GREEN
                connState == ConnState.CONNECTING -> Pal.AMBER
                !ble.isSupported() || !ble.isEnabled() -> Pal.RED
                else -> Pal.MUTED
            }
        )
        statusBadge.background = roundRect(
            Pal.SURFACE, 999,
            if (connected) ColorUtils.withAlpha(Pal.GREEN, 0x55) else Pal.STROKE
        )
        subtitle.text = when {
            connected -> "$connName · ${gattServices.size} сервисов"
            activeProfile != null -> "Профиль: ${activeProfile?.name}"
            else -> "Bluetooth-пульт для любых устройств"
        }
    }

    private fun toast(message: String) {
        Toast.makeText(this, message, Toast.LENGTH_SHORT).show()
    }

    // ---------- Разрешения и включение Bluetooth ----------

    private fun requestBlePermissions() {
        if (ble.missingPermissions().isEmpty()) return
        requestPermissions(ble.requiredPermissions(), REQ_BLE)
    }

    private fun ensureBle(andThen: () -> Unit) {
        if (!ble.isSupported()) {
            toast("Этот телефон не поддерживает Bluetooth")
            return
        }
        if (ble.isEnabled()) {
            andThen()
            return
        }
        pendingAfterEnable = andThen
        try {
            startActivityForResult(Intent(BluetoothAdapter.ACTION_REQUEST_ENABLE), REQ_ENABLE_BT)
        } catch (e: Exception) {
            try {
                startActivity(Intent(Settings.ACTION_BLUETOOTH_SETTINGS))
            } catch (ignored: Exception) {
                toast("Включите Bluetooth в настройках телефона")
            }
        }
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == REQ_BLE || requestCode == REQ_WIFI) {
            val next = pendingAfterPermission
            pendingAfterPermission = null
            if (requestCode == REQ_WIFI) {
                next?.invoke()
            } else if (ble.missingPermissions().isEmpty()) {
                next?.invoke() ?: run { startScan() }
            } else {
                toast("Без разрешений Bluetooth не сможет искать устройства")
            }
            rebuild()
        }
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == REQ_ENABLE_BT) {
            val next = pendingAfterEnable
            pendingAfterEnable = null
            if (ble.isEnabled()) next?.invoke() else toast("Bluetooth остался выключен")
            rebuild()
        }
        if (requestCode == REQ_WRITE_STORAGE) {
            val file = pendingGalleryExport
            pendingGalleryExport = null
            if (file != null) exportPhoto(file)
        }
    }

    // ---------- Скан ----------

    private fun startScan() {
        if (!ble.isSupported()) {
            toast("Bluetooth не поддерживается")
            return
        }
        val missing = ble.missingPermissions()
        if (missing.isNotEmpty()) {
            pendingAfterPermission = {
                ensureBle {
                    scanMessage = null
                    ble.startScan()
                    rebuild()
                }
            }
            requestPermissions(missing.toTypedArray(), REQ_BLE)
            return
        }
        ensureBle {
            scanMessage = null
            ble.startScan()
            tab = TAB_SCAN
            rebuild()
        }
    }

    private fun connectTo(item: ScanItem) {
        if (item.demo) {
            connectDemo()
            return
        }
        if (ble.missingPermissions().isNotEmpty()) {
            pendingAfterPermission = { connectTo(item) }
            requestPermissions(ble.requiredPermissions(), REQ_BLE)
            return
        }
        ensureBle {
            activeProfile = profiles.bestFor(item)
            saveActiveProfile()
            captureStatus = "Готов к съёмке"
            captureDetail = ""
            ble.connect(item)
            tab = TAB_DEVICE
            rebuild()
        }
    }

    private fun connectDemo() {
        ble.stopScan()
        ble.disconnect()
        connState = ConnState.CONNECTED
        connName = "Демо: умные очки RayX"
        connAddress = DemoDevice.ADDRESS
        gattServices = DemoDevice.services()
        batteryPercent = 78
        batteryAttempted = true
        activeProfile = profiles.byId("demo_glasses") ?: profiles.ensureLoaded().firstOrNull { it.hasCamera }
        saveActiveProfile()
        captureStatus = "Готов к съёмке"
        captureDetail = "Виртуальное устройство: снимок придёт из памяти телефона."
        addLog("Демо-очки подключены (без железа)")
        tab = TAB_DEVICE
        rebuild()
    }

    private fun doDisconnect() {
        connState = ConnState.DISCONNECTED
        gattServices = emptyList()
        batteryPercent = null
        subscribed.clear()
        if (DemoDevice.isDemo(connAddress)) {
            connAddress = ""
            connName = ""
            addLog("Демо-очки отключены")
            rebuild()
        } else {
            ble.disconnect()
        }
    }

    private fun saveActiveProfile() {
        prefs.edit().putString("active_profile", activeProfile?.id).apply()
    }

    // ---------- Колбэки BLE ----------

    override fun onScan(list: List<ScanItem>) {
        scanItems.clear()
        scanItems.addAll(list)
        if (scanMessage == null && list.isEmpty()) scanMessage = "Пока никого не видно. Убедитесь, что устройство включено и рядом."
        if (tab == TAB_SCAN) rebuild()
    }

    override fun onScanState(scanning: Boolean, message: String?) {
        this.scanning = scanning
        if (message != null) scanMessage = message
        if (tab == TAB_SCAN) rebuild()
    }

    override fun onConnection(state: ConnState, name: String, address: String) {
        connState = state
        if (name.isNotEmpty()) connName = name
        if (address.isNotEmpty() && state != ConnState.DISCONNECTED) connAddress = address
        if (state == ConnState.CONNECTING) {
            gattServices = emptyList()
            batteryPercent = null
            batteryAttempted = false
        }
        if (state == ConnState.DISCONNECTED) {
            gattServices = emptyList()
            batteryPercent = null
            batteryAttempted = false
            subscribed.clear()
            if (DemoDevice.isDemo(address)) connAddress = ""
        }
        rebuild()
    }

    override fun onServices(services: List<GattServiceInfo>) {
        gattServices = services
        if (activeProfile == null) {
            val item = scanItems.firstOrNull { it.address == connAddress }
            if (item != null) {
                activeProfile = profiles.bestFor(item)
                saveActiveProfile()
            }
        }
        readBatteryIfPresent()
        rebuild()
    }

    override fun onCharValue(service: UUID, char: UUID, value: ByteArray) {
        camera.feed(service, char, value)
        if (GattNames.shortCode(char) == 0x2A19 && value.isNotEmpty()) {
            batteryPercent = value[0].toInt() and 0xFF
        }
        // Во время передачи снимка уведомления идут потоком: журнал не засоряем и экран не дёргаем.
        if (camera.isCapturing()) return
        val text = GattNames.describe(char, value) ?: bytesToHex(value.take(24).toByteArray())
        addLog("→ ${GattNames.charName(char)}: $text")
        if (tab == TAB_GATT || tab == TAB_DEVICE) rebuildThrottled()
    }

    override fun onCharWritten(service: UUID, char: UUID, ok: Boolean) {
        if (tab == TAB_GATT) rebuild()
    }

    override fun onLog(line: String) {
        addLog(line)
    }

    private fun addLog(line: String) {
        val stamp = SimpleDateFormat("HH:mm:ss", Locale.US).format(Date())
        logs.add("$stamp  $line")
        while (logs.size > 300) logs.removeAt(0)
        val view = consoleLogView
        if (tab == TAB_CONSOLE && view != null) {
            view.text = logs.joinToString("\n")
            consoleScroll?.post { consoleScroll?.fullScroll(View.FOCUS_DOWN) }
        }
    }

    // ---------- Камера: колбэки ----------

    override fun onCaptureStatus(status: String, detail: String) {
        ui.post {
            captureStatus = status
            captureDetail = detail
            if (tab == TAB_CAMERA || tab == TAB_DEVICE) rebuild()
        }
    }

    override fun onPhoto(file: File, bytes: ByteArray, source: String) {
        ui.post {
            lastPhoto = file
            lastPhotoBitmap = thumb(file, 320)
            addLog("Снимок сохранён: ${file.name} (${bytes.size / 1024} КБ)")
            if (tab == TAB_CAMERA || tab == TAB_PHOTOS || tab == TAB_DEVICE) rebuild()
        }
    }

    override fun onCameraLog(line: String) {
        ui.post { addLog(line) }
    }

    private fun captureWith(profile: DeviceProfile?) {
        if (profile == null || profile.camera == null) {
            toast("Нет профиля с камерой")
            return
        }
        val spec = profile.camera
        if (spec.mode == "ble" && !DemoDevice.isDemo(connAddress) &&
            connState != ConnState.CONNECTED
        ) {
            toast("Сначала подключитесь к устройству")
            return
        }
        // Wi-Fi путь требует разрешений: на Android 12 и ниже — геолокация, на 13+ — nearby Wi-Fi.
        if (spec.mode == "http") {
            val need = ArrayList<String>()
            if (Build.VERSION.SDK_INT <= 32) need.add(Manifest.permission.ACCESS_FINE_LOCATION)
            if (Build.VERSION.SDK_INT >= 33) need.add(Manifest.permission.NEARBY_WIFI_DEVICES)
            val missing = need.filter {
                checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED
            }
            if (missing.isNotEmpty()) {
                pendingAfterPermission = { captureWith(profile) }
                requestPermissions(missing.toTypedArray(), REQ_WIFI)
                return
            }
        }
        activeProfile = profile
        saveActiveProfile()
        camera.capture(profile)
        tab = TAB_CAMERA
        rebuild()
    }

    // ---------- Вкладка «Поиск» ----------

    private fun buildScanTab(): View {
        val c = column()

        if (!ble.isSupported()) {
            c.addView(hintCard("Bluetooth не поддерживается", "На этом телефоне нет Bluetooth-адаптера, поэтому поиск устройств недоступен. Демо-режим всё равно можно открыть."))
        } else if (!ble.isEnabled()) {
            c.addView(hintCard("Bluetooth выключен", "Включите адаптер, чтобы искать наушники, часы, очки и датчики.", "Включить Bluetooth") {
                ensureBle { startScan() }
            })
        } else if (ble.missingPermissions().isNotEmpty()) {
            c.addView(hintCard("Нужны разрешения", "Android спрашивает их для поиска и подключения к Bluetooth-устройствам поблизости.", "Разрешить") {
                requestBlePermissions()
            })
        }

        val buttons = row()
        buttons.addView(actionButton(if (scanning) "Остановить" else "Сканировать", primary = !scanning) {
            if (scanning) ble.stopScan() else startScan()
        })
        buttons.addView(actionButton("Демо-очки") { connectDemo() })
        c.addView(buttons)
        c.addView(spacer(6))

        scanMessage?.let {
            c.addView(txt(it, 12, Pal.AMBER))
            c.addView(spacer(6))
        }

        val items = ArrayList(scanItems)
        if (items.none { it.demo }) items.add(0, DemoDevice.scanItem())
        c.addView(section("Устройства рядом · ${items.size}"))
        for (item in items) c.addView(deviceCard(item))

        c.addView(spacer(4))
        c.addView(
            hintCard(
                "Совет",
                "Держите устройство рядом и включите на нём режим сопряжения. Уже сопряжённые наушники и часы видны в списке сразу — они помечены как «сопряжено»."
            )
        )
        return c
    }

    private fun deviceCard(item: ScanItem): View {
        val card = card()
        val head = row()
        head.addView(txt(if (item.demo) "🕶" else if (item.classic) "🎧" else "📶", 20))
        head.addView(hspace(10))
        val names = column()
        names.addView(txt(item.label, 15, Pal.TEXT, bold = true))
        val sub = if (item.demo) "виртуальное устройство" else "${item.address} · ${item.rssi} dBm"
        names.addView(txt(sub, 11, Pal.MUTED, mono = true))
        head.addView(names, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        card.addView(head)

        val tags = row()
        if (item.demo) tags.addView(badge("демо", Pal.ACCENT))
        if (item.classic) tags.addView(badge("сопряжено", Pal.AMBER))
        if (item.serviceUuids.isNotEmpty()) tags.addView(badge("реклама: ${item.serviceUuids.size} серв.", Pal.MUTED))
        val profile = profiles.bestFor(item)
        if (profile != null) tags.addView(badge(profile.name, Pal.VIOLET))
        card.addView(tags)
        card.addView(spacer(8))

        val connected = connState == ConnState.CONNECTED && connAddress == item.address
        val actions = row()
        actions.addView(
            actionButton(
                when {
                    connected -> "Открыть устройство"
                    connState == ConnState.CONNECTING && connAddress == item.address -> "Соединение…"
                    else -> "Подключиться"
                },
                primary = !connected
            ) {
                if (connected) {
                    tab = TAB_DEVICE
                    rebuild()
                } else {
                    connectTo(item)
                }
            }
        )
        card.addView(actions)
        card.setOnClickListener {
            val sheet = column()
            sheet.addView(txt(item.label, 16, Pal.TEXT, bold = true))
            sheet.addView(txt(item.address, 12, Pal.MUTED, mono = true))
            sheet.addView(spacer(8))
            sheet.addView(txt(if (item.demo) "Виртуальные очки внутри приложения: показывают, как работает камера без железа." else "Обычное BLE-устройство. После подключения откроются все его сервисы и характеристики.", 13, Pal.TEXT))
            profile?.let {
                sheet.addView(spacer(8))
                sheet.addView(txt("Профиль: ${it.name}", 13, Pal.VIOLET))
            }
            showSheet("Устройство", sheet)
        }
        return card
    }

    // ---------- Вкладка «Устройство» ----------

    private fun buildDeviceTab(): View {
        val c = column()
        if (connAddress.isEmpty() && connState != ConnState.CONNECTED) {
            c.addView(hintCard("Нет подключения", "Найдите устройство во вкладке «Поиск» или откройте демо-очки, чтобы посмотреть, как всё работает.") )
            c.addView(actionButton("Открыть демо-очки", primary = true) { connectDemo() })
            return c
        }

        val connected = connState == ConnState.CONNECTED
        val info = card()
        val head = row()
        head.addView(txt(connName, 16, Pal.TEXT, bold = true), LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        head.addView(badge(if (connected) "на связи" else "нет связи", if (connected) Pal.GREEN else Pal.RED))
        info.addView(head)
        info.addView(txt(connAddress, 11, Pal.MUTED, mono = true))
        info.addView(spacer(8))
        val meta = row()
        meta.addView(badge("сервисов: ${gattServices.size}", Pal.ACCENT))
        meta.addView(badge("MTU ${ble.mtu}", Pal.MUTED))
        if (DemoDevice.isDemo(connAddress)) meta.addView(badge("демо", Pal.VIOLET))
        info.addView(meta)
        info.addView(spacer(10))
        val buttons = row()
        buttons.addView(actionButton("Отключить", primary = false) { doDisconnect() })
        if (connected && !DemoDevice.isDemo(connAddress)) {
            buttons.addView(actionButton("Перечитать GATT") { ble.refreshServices() })
        }
        buttons.addView(actionButton("Все сервисы") {
            tab = TAB_GATT
            rebuild()
        })
        info.addView(buttons)
        c.addView(info)

        // Батарея
        if (batteryPercent != null || batteryCharAvailable()) {
            val battery = card()
            val rowB = row()
            rowB.addView(txt("🔋", 22))
            rowB.addView(hspace(10))
            rowB.addView(txt(batteryPercent?.let { "$it%" } ?: "—", 24, Pal.GREEN, bold = true))
            rowB.addView(hspace(10))
            val box = column()
            box.addView(txt("Батарея устройства", 13, Pal.TEXT))
            box.addView(txt("стандартная характеристика Battery Level", 11, Pal.MUTED))
            rowB.addView(box, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
            rowB.addView(pill("Обновить", false) { readBattery() })
            battery.addView(rowB)
            c.addView(battery)
        }

        // Профиль
        val profile = activeProfile
        if (profile != null) {
            val p = card()
            val ph = row()
            ph.addView(txt("Профиль устройства", 12, Pal.MUTED, bold = true), LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
            ph.addView(badge(profile.cameraModeText, if (profile.hasCamera) Pal.GREEN else Pal.MUTED))
            p.addView(ph)
            p.addView(txt(profile.name, 16, Pal.TEXT, bold = true))
            if (profile.vendor.isNotBlank()) p.addView(txt(profile.vendor, 12, Pal.VIOLET))
            if (profile.description.isNotBlank()) {
                p.addView(spacer(6))
                p.addView(txt(profile.description, 12, Pal.MUTED))
            }
            p.addView(spacer(8))
            val caps = row()
            for (cap in profile.capabilities) caps.addView(badge(capTitle(cap), capColor(cap)))
            p.addView(caps)
            if (profile.hasCamera) {
                p.addView(spacer(10))
                p.addView(actionButton("📷 " + (profile.camera?.label ?: "Снять"), primary = true) {
                    captureWith(profile)
                })
            }
            if (profile.notes.isNotEmpty()) {
                p.addView(spacer(8))
                for (note in profile.notes) p.addView(txt("· $note", 11, Pal.MUTED))
            }
            c.addView(p)
        } else {
            c.addView(hintCard("Профиль не подобран", "Устройство подключено, но приложение не знает его возможностей. Можно посмотреть все характеристики вручную или создать свой профиль.") )
            c.addView(actionButton("Создать профиль", primary = false) { openEditor(null) })
        }

        c.addView(
            hintCard(
                "Что дальше",
                "Вкладка «GATT» показывает всё, что умеет устройство: батарею, датчики, кнопки, камеру. Любую характеристику можно прочитать или записать."
            )
        )
        return c
    }

    private fun batteryCharAvailable(): Boolean {
        if (activeProfile?.batteryChar != null) return true
        return gattServices.any { svc ->
            GattNames.shortCode(svc.uuid) == 0x180F || svc.chars.any { GattNames.shortCode(it.uuid) == 0x2A19 }
        }
    }

    private fun readBatteryIfPresent() {
        if (batteryAttempted || batteryPercent != null) return
        if (!batteryCharAvailable()) return
        batteryAttempted = true
        val profile = activeProfile
        val char = profile?.batteryChar ?: gattServices
            .firstOrNull { GattNames.shortCode(it.uuid) == 0x180F }
            ?.chars?.firstOrNull { GattNames.shortCode(it.uuid) == 0x2A19 }?.uuid
            ?: gattServices.flatMap { it.chars }.firstOrNull { GattNames.shortCode(it.uuid) == 0x2A19 }?.uuid
            ?: return
        val service = profile?.batteryService
            ?: gattServices.firstOrNull { s -> s.chars.any { it.uuid == char } }?.uuid
        if (DemoDevice.isDemo(connAddress)) {
            batteryPercent = 78
            return
        }
        ble.read(service, char)
    }

    private fun readBattery() {
        val profile = activeProfile
        val char = profile?.batteryChar
            ?: gattServices.flatMap { it.chars }.firstOrNull { GattNames.shortCode(it.uuid) == 0x2A19 }?.uuid
        if (char == null) {
            toast("Это устройство не сообщает уровень батареи")
            return
        }
        val service = profile?.batteryService
            ?: gattServices.firstOrNull { s -> s.chars.any { it.uuid == char } }?.uuid
        if (DemoDevice.isDemo(connAddress)) {
            batteryPercent = 78
            rebuild()
            return
        }
        ble.read(service, char)
    }

    // ---------- Вкладка «Камера» ----------

    private fun buildCameraTab(): View {
        val c = column()
        val profile = activeProfile ?: profiles.byId("demo_glasses")

        if (profile == null || profile.camera == null) {
            c.addView(hintCard("Камера не настроена", "У активного профиля нет камеры. Подключите очки или выберите профиль с камерой — например, встроенный демо-профиль."))
            c.addView(actionButton("Взять демо-очки", primary = true) { connectDemo() })
            c.addView(spacer(6))
            c.addView(actionButton("Открыть профили", primary = false) {
                tab = TAB_PROFILES
                rebuild()
            })
            return c
        }

        val cam = profile.camera
        val cardTop = card()
        val head = row()
        head.addView(txt(profile.name, 16, Pal.TEXT, bold = true), LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        head.addView(badge(profile.cameraModeText, Pal.GREEN))
        cardTop.addView(head)
        cardTop.addView(txt("Способ: ${modeHint(cam.mode)}", 11, Pal.MUTED))
        cardTop.addView(spacer(10))
        cardTop.addView(txt(captureStatus, 18, Pal.TEXT, bold = true))
        if (captureDetail.isNotBlank()) cardTop.addView(txt(captureDetail, 12, Pal.MUTED))
        cardTop.addView(spacer(12))
        cardTop.addView(
            actionButton("📸 " + cam.label, primary = true) { captureWith(profile) }
        )
        if (captureStatus.startsWith("Готово", ignoreCase = true)) {
            cardTop.addView(spacer(4))
            cardTop.addView(txt("Снимок сохранён во вкладке «Фото».", 11, Pal.GREEN))
        }
        c.addView(cardTop)

        lastPhoto?.let { file ->
            val photoCard = card()
            photoCard.addView(txt("Последний снимок", 12, Pal.MUTED, bold = true))
            photoCard.addView(spacer(8))
            val image = ImageView(this)
            image.scaleType = ImageView.ScaleType.CENTER_CROP
            image.setBackgroundColor(Pal.SURFACE_2)
            lastPhotoBitmap?.let { image.setImageBitmap(it) }
            photoCard.addView(image, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(170)))
            photoCard.addView(spacer(8))
            val actions = row()
            actions.addView(actionButton("Открыть", primary = true) { openPhoto(file) })
            actions.addView(actionButton("Все фото", primary = false) {
                tab = TAB_PHOTOS
                rebuild()
            })
            photoCard.addView(actions)
            c.addView(photoCard)
        }

        c.addView(
            hintCard(
                "Как это работает",
                when (cam.mode) {
                    "ble" -> "Приложение отправляет команду в характеристику-триггер и собирает JPEG из уведомлений характеристики данных. UUID задаются в профиле."
                    "http" -> "Очки поднимают Wi-Fi точку доступа, телефон подключается к ней и забирает снимок по HTTP. SSID и адрес задаются в профиле."
                    else -> "Демо-режим: снимок берётся из памяти телефона. Так можно проверить весь путь без железных очков."
                }
            )
        )
        return c
    }

    private fun modeHint(mode: String): String = when (mode) {
        "ble" -> "BLE-команда → поток JPEG в уведомлениях"
        "http" -> "Wi-Fi точка доступа очков → HTTP-снимок"
        else -> "встроенная демонстрация"
    }

    private fun openPhoto(file: File) {
        startActivity(Intent(this, PhotoActivity::class.java).putExtra("path", file.path))
    }

    // ---------- Вкладка «GATT» ----------

    private fun buildGattTab(): View {
        val c = column()
        val head = row()
        head.addView(txt("Сервисы и характеристики", 16, Pal.TEXT, bold = true), LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        head.addView(pill("Перечитать", false) {
            if (DemoDevice.isDemo(connAddress)) {
                gattServices = DemoDevice.services()
                rebuild()
            } else {
                ble.refreshServices()
            }
        })
        c.addView(head)

        if (gattServices.isEmpty()) {
            c.addView(hintCard("Список пуст", "Подключитесь к устройству — сервисы появятся здесь автоматически. У стандартных устройств видно батарею, датчики и служебную информацию.") )
            return c
        }

        c.addView(txt("R — чтение, W — запись, N — уведомления", 11, Pal.MUTED))
        c.addView(spacer(8))

        for (svc in gattServices) {
            val card = card(12)
            val top = row()
            top.addView(txt(GattNames.serviceName(svc.uuid), 14, Pal.TEXT, bold = true), LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
            top.addView(badge(GattNames.shortHex(svc.uuid), Pal.ACCENT))
            card.addView(top)
            card.addView(txt(svc.uuid.toString(), 10, Pal.MUTED, mono = true))
            card.addView(spacer(4))
            for (ch in svc.chars) card.addView(charRow(svc.uuid, ch))
            c.addView(card)
        }
        return c
    }

    private fun charRow(service: UUID, ch: GattCharInfo): View {
        val block = column()
        block.setPadding(0, dp(10), 0, dp(2))

        val top = row()
        top.addView(txt(GattNames.charName(ch.uuid), 13, Pal.TEXT, bold = true), LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        top.addView(badge(ch.props(), Pal.GREEN))
        block.addView(top)
        block.addView(txt(GattNames.uuidLabel(ch.uuid), 10, Pal.MUTED, mono = true))

        ch.value?.let { v ->
            val head = v.take(24).toByteArray()
            block.addView(txt(bytesToHex(head) + "  |" + bytesToAscii(head) + "|", 10, Pal.MUTED, mono = true))
            GattNames.describe(ch.uuid, v)?.let { block.addView(txt(it, 12, Pal.GREEN, bold = true)) }
        }

        val actions = row()
        if (ch.readable) actions.addView(pill("Читать", false) { doRead(service, ch.uuid) })
        if (ch.writable) actions.addView(pill("Писать", false) { showWriteDialog(service, ch.uuid) })
        if (ch.notifiable) {
            val key = "$service|${ch.uuid}"
            actions.addView(pill(if (subscribed.contains(key)) "Отписаться" else "Слушать", subscribed.contains(key)) {
                toggleSubscribe(service, ch.uuid)
            })
        }
        actions.addView(pill("→ Консоль", false) {
            consoleService = service
            consoleChar = ch.uuid
            consoleTextMode = false
            toast("Характеристика выбрана")
            tab = TAB_CONSOLE
            rebuild()
        })
        val strip = HorizontalScrollView(this)
        strip.isHorizontalScrollBarEnabled = false
        strip.addView(actions)
        block.addView(spacer(4))
        block.addView(strip)
        return block
    }

    private fun doRead(service: UUID, char: UUID) {
        if (DemoDevice.isDemo(connAddress)) {
            val value = DemoDevice.readValue(char)
            if (value != null) {
                onCharValue(service, char, value)
            } else {
                toast("Демо: у этой характеристики нет значения")
            }
            return
        }
        ble.read(service, char)
    }

    private fun doWrite(service: UUID?, char: UUID, payload: ByteArray) {
        if (DemoDevice.isDemo(connAddress)) {
            addLog("Демо: записано ${payload.size} байт в ${GattNames.charName(char)}")
            toast("Демо: команда отправлена")
            rebuild()
            return
        }
        ble.write(service, char, payload)
    }

    private fun toggleSubscribe(service: UUID, char: UUID) {
        val key = "$service|$char"
        val enable = !subscribed.contains(key)
        if (enable) subscribed.add(key) else subscribed.remove(key)
        if (DemoDevice.isDemo(connAddress)) {
            addLog("Демо: ${if (enable) "подписка на" else "отписка от"} ${GattNames.charName(char)}")
            rebuild()
            return
        }
        ble.subscribe(service, char, enable)
        rebuild()
    }

    private fun showWriteDialog(service: UUID?, char: UUID) {
        val body = column()
        body.addView(txt("Введите байты в hex (01 FF 7A) или текст с префиксом text:", 12, Pal.MUTED))
        body.addView(spacer(8))
        val field = input("01", "01")
        body.addView(field)
        val chips = row()
        chips.addView(pill("01", false) { field.setText("01") })
        chips.addView(pill("00", false) { field.setText("00") })
        chips.addView(pill("text:ON", false) { field.setText("text:ON") })
        body.addView(chips)
        showSheet("Записать в ${GattNames.charName(char)}", body, "Записать") {
            val raw = field.text.toString()
            try {
                doWrite(service, char, parsePayload(raw))
            } catch (e: Exception) {
                toast("Не понял данные: ${e.message}")
            }
        }
    }

    // ---------- Вкладка «Профили» ----------

    private fun buildProfilesTab(): View {
        val c = column()
        val actions = row()
        actions.addView(actionButton("Создать профиль", primary = true) { openEditor(null) })
        actions.addView(actionButton("Импорт JSON", primary = false) { openImportDialog() })
        c.addView(actions)
        c.addView(txt("Профиль — это правила общения с устройством: как снимать фото, где батарея, по каким UUID искать устройство. Скопируйте JSON и передайте другу.", 11, Pal.MUTED))
        c.addView(spacer(10))

        val builtins = profiles.all.filter { it.builtIn }
        val users = profiles.all.filter { !it.builtIn }

        c.addView(section("Встроенные"))
        for (p in builtins) c.addView(profileCard(p, editable = false))

        c.addView(section("Мои профили"))
        if (users.isEmpty()) {
            c.addView(txt("Пока пусто. Создайте профиль под свои очки — или начните с шаблона в редакторе.", 12, Pal.MUTED))
        }
        for (p in users) c.addView(profileCard(p, editable = true))
        c.addView(spacer(8))
        c.addView(
            hintCard(
                "Зачем профили",
                "Любое устройство можно изучить вручную в GATT. Профиль сохраняет найденные UUID и превращает их в кнопку «Снять фото» или «Показать батарею»."
            )
        )
        return c
    }

    private fun profileCard(p: DeviceProfile, editable: Boolean): View {
        val card = card()
        val head = row()
        head.addView(txt(p.name, 15, Pal.TEXT, bold = true), LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        if (activeProfile?.id == p.id) head.addView(badge("активен", Pal.GREEN))
        card.addView(head)
        if (p.vendor.isNotBlank()) card.addView(txt(p.vendor, 11, Pal.VIOLET))
        if (p.description.isNotBlank()) {
            card.addView(spacer(4))
            card.addView(txt(p.description, 12, Pal.MUTED))
        }
        card.addView(spacer(6))
        val tags = row()
        tags.addView(badge(p.cameraModeText, if (p.hasCamera) Pal.GREEN else Pal.MUTED))
        if (p.batteryChar != null) tags.addView(badge("батарея", Pal.ACCENT))
        if (p.namePrefixes.isNotEmpty()) tags.addView(badge("имя: ${p.namePrefixes.joinToString(", ")}", Pal.MUTED))
        card.addView(tags)
        card.addView(spacer(10))
        val actions = row()
        actions.addView(pill("Выбрать", false) {
            activeProfile = p
            saveActiveProfile()
            addLog("Активный профиль: ${p.name}")
            rebuild()
        })
        actions.addView(pill("JSON", false) { showJsonDialog(p) })
        if (editable) {
            actions.addView(pill("Изменить", false) { openEditor(p) })
            actions.addView(pill("Удалить", false) {
                profiles.deleteUser(p.id)
                if (activeProfile?.id == p.id) {
                    activeProfile = null
                    saveActiveProfile()
                }
                addLog("Профиль удалён: ${p.name}")
                rebuild()
            })
        }
        val strip = HorizontalScrollView(this)
        strip.isHorizontalScrollBarEnabled = false
        strip.addView(actions)
        card.addView(strip)
        return card
    }

    private fun showJsonDialog(p: DeviceProfile) {
        val body = column()
        val json = p.toJson().toString(2)
        val view = txt(json, 10, Pal.MUTED, mono = true)
        val scroll = ScrollView(this)
        scroll.addView(view)
        body.addView(scroll, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(240)))
        body.addView(spacer(8))
        body.addView(pill("Копировать JSON", false) {
            copyToClipboard(json)
            toast("JSON скопирован")
        })
        showSheet(p.name, body)
    }

    private fun copyToClipboard(text: String) {
        val cm = getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager ?: return
        cm.setPrimaryClip(ClipData.newPlainText("BlueLink профиль", text))
    }

    private fun openImportDialog() {
        val body = column()
        body.addView(txt("Вставьте JSON профиля", 12, Pal.MUTED))
        val field = input("{\n  \"name\": \"Мои очки\",\n  \"camera\": { \"mode\": \"http\", \"httpUrl\": \"http://192.168.4.1/photo.jpg\" }\n}", "", multiline = true)
        body.addView(field)
        body.addView(pill("Вставить пример", false) {
            field.setText(exampleProfileJson())
        })
        showSheet("Импорт профиля", body, "Импортировать") {
            val imported = profiles.importJson(field.text.toString())
            if (imported == null) {
                toast("Не получилось: проверьте JSON и поле name")
            } else {
                addLog("Импортирован профиль: ${imported.name}")
                toast("Профиль «${imported.name}» добавлен")
                rebuild()
            }
        }
    }

    private fun exampleProfileJson(): String = """
        {
          "id": "user_my_glasses",
          "name": "Мои очки с камерой",
          "vendor": "DIY",
          "description": "Очки на ESP32: камера по Wi-Fi",
          "match": { "namePrefixes": ["Glass"] },
          "capabilities": ["camera", "battery"],
          "battery": { "service": "180f", "characteristic": "2a19" },
          "camera": {
            "mode": "http",
            "label": "Снять фото",
            "httpUrl": "http://192.168.4.1/photo.jpg",
            "wifiSsid": "GlassCam",
            "wifiPassword": "12345678",
            "waitMs": 1500
          },
          "notes": ["Светодиод мигает — идёт съёмка"]
        }
    """.trimIndent()

    // ---------- Редактор профиля ----------

    private fun openEditor(existing: DeviceProfile?) {
        val isCopy = existing?.builtIn == true
        val base = existing
        val body = column()
        var mode = base?.camera?.mode ?: "none"

        body.addView(label("Название профиля"))
        val name = input("Мои умные очки", base?.name ?: "")
        body.addView(name)

        body.addView(label("Производитель (необязательно)"))
        val vendor = input("Например, RayX", base?.vendor ?: "")
        body.addView(vendor)

        body.addView(label("Описание"))
        val description = input("Что это за устройство", base?.description ?: "")
        body.addView(description)

        body.addView(label("Совпадение по имени (через запятую)"))
        val prefixes = input("RayX, Glass, Frame", base?.namePrefixes?.joinToString(", ") ?: "")
        body.addView(prefixes)

        body.addView(label("UUID сервисов для поиска (через запятую)"))
        val services = input("ffe0, 180f", base?.serviceUuids?.joinToString(", ") { shortOrFullUuid(it) } ?: "")
        body.addView(services)

        body.addView(label("Батарея: UUID сервиса"))
        val batteryService = input("180f", base?.batteryService?.let { shortOrFullUuid(it) } ?: "")
        body.addView(batteryService)

        body.addView(label("Батарея: UUID характеристики"))
        val batteryChar = input("2a19", base?.batteryChar?.let { shortOrFullUuid(it) } ?: "")
        body.addView(batteryChar)

        body.addView(label("Камера"))
        val modeRow = row()
        fun refreshModes() {
            modeRow.removeAllViews()
            for ((id, title) in listOf(
                "none" to "Нет",
                "demo" to "Демо",
                "ble" to "BLE",
                "http" to "Wi-Fi/HTTP"
            )) {
                modeRow.addView(pill(title, mode == id) {
                    mode = id
                    refreshModes()
                })
            }
        }
        refreshModes()
        body.addView(modeRow)
        body.addView(spacer(8))

        body.addView(label("Название кнопки съёмки"))
        val cameraLabel = input("Снять фото", base?.camera?.label ?: "Снять фото")
        body.addView(cameraLabel)

        body.addView(label("Камера: UUID сервиса"))
        val cameraService = input("ffe0", base?.camera?.service?.let { shortOrFullUuid(it) } ?: "")
        body.addView(cameraService)

        body.addView(label("Камера: характеристика-триггер (для BLE)"))
        val triggerChar = input("ffe1", base?.camera?.triggerChar?.let { shortOrFullUuid(it) } ?: "")
        body.addView(triggerChar)

        body.addView(label("Камера: характеристика данных (для BLE)"))
        val dataChar = input("ffe2", base?.camera?.dataChar?.let { shortOrFullUuid(it) } ?: "")
        body.addView(dataChar)

        body.addView(label("Команда съёмки, hex"))
        val trigger = input("01", base?.camera?.let { bytesToHex(it.trigger) } ?: "01")
        body.addView(trigger)

        body.addView(label("Формат потока: jpeg или sizeHeader"))
        val framing = input("jpeg", base?.camera?.framing ?: "jpeg")
        body.addView(framing)

        body.addView(label("Wi-Fi: адрес снимка (для HTTP)"))
        val httpUrl = input("http://192.168.4.1/photo.jpg", base?.camera?.httpUrl ?: "")
        body.addView(httpUrl)

        body.addView(label("Wi-Fi: имя сети очков"))
        val wifiSsid = input("GlassCam", base?.camera?.wifiSsid ?: "")
        body.addView(wifiSsid)

        body.addView(label("Wi-Fi: пароль"))
        val wifiPass = input("12345678", base?.camera?.wifiPassword ?: "")
        body.addView(wifiPass)

        body.addView(label("Пауза перед скачиванием, мс"))
        val waitMs = input("1200", (base?.camera?.waitMs ?: 1200).toString())
        body.addView(waitMs)

        val scroll = ScrollView(this)
        scroll.addView(body)

        showSheet(if (existing == null) "Новый профиль" else "Профиль: ${existing.name}", scroll, "Сохранить") {
            val profileName = name.text.toString().trim()
            if (profileName.isEmpty()) {
                toast("Нужно название профиля")
                return@showSheet
            }
            val id = if (existing == null || isCopy) profiles.nextUserId() else existing.id
            val camSpec = if (mode == "none") null else CameraSpec(
                mode = mode,
                label = cameraLabel.text.toString().trim().ifBlank { "Снять фото" },
                service = parseUuid(cameraService.text.toString()),
                triggerChar = parseUuid(triggerChar.text.toString()),
                dataChar = parseUuid(dataChar.text.toString()),
                trigger = try {
                    parsePayload(trigger.text.toString().ifBlank { "01" })
                } catch (e: Exception) {
                    byteArrayOf(0x01)
                },
                framing = framing.text.toString().trim().ifBlank { "jpeg" },
                httpUrl = httpUrl.text.toString().trim(),
                wifiSsid = wifiSsid.text.toString().trim(),
                wifiPassword = wifiPass.text.toString(),
                waitMs = waitMs.text.toString().toIntOrNull() ?: 1200,
                demoAsset = "demo/glasses_photo.jpg"
            )
            val profile = DeviceProfile(
                id = id,
                name = profileName,
                vendor = vendor.text.toString().trim(),
                description = description.text.toString().trim(),
                namePrefixes = prefixes.text.toString().split(",").map { it.trim() }.filter { it.isNotEmpty() },
                serviceUuids = services.text.toString().split(",").mapNotNull { parseUuid(it) },
                capabilities = buildList {
                    if (batteryChar.text.toString().isNotBlank()) add("battery")
                    if (camSpec != null) add("camera")
                    add("device_info")
                },
                batteryService = parseUuid(batteryService.text.toString()),
                batteryChar = parseUuid(batteryChar.text.toString()),
                camera = camSpec,
                notes = existing?.notes ?: emptyList(),
                builtIn = false
            )
            profiles.saveUser(profile)
            activeProfile = profile
            saveActiveProfile()
            addLog("Профиль сохранён: ${profile.name}")
            toast("Профиль сохранён")
            rebuild()
        }
    }

    // ---------- Вкладка «Фото» ----------

    private fun buildPhotosTab(): View {
        val c = column()
        val files = store.list()
        val head = row()
        head.addView(txt("Снимки · ${files.size}", 16, Pal.TEXT, bold = true), LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        head.addView(pill("Обновить", false) { rebuild() })
        c.addView(head)

        if (files.isEmpty()) {
            c.addView(hintCard("Пока нет снимков", "Откройте вкладку «Камера» и нажмите кнопку съёмки. Снимок появится здесь и его можно сохранить в галерею."))
            return c
        }

        for (f in files.take(60)) {
            val card = card(10)
            val row = row()
            val image = ImageView(this)
            image.scaleType = ImageView.ScaleType.CENTER_CROP
            image.setBackgroundColor(Pal.SURFACE_2)
            image.loadThumb(f, 160)
            row.addView(image, LinearLayout.LayoutParams(dp(72), dp(72)))
            row.addView(hspace(12))
            val info = column()
            val date = SimpleDateFormat("d MMM, HH:mm:ss", Locale("ru")).format(Date(f.lastModified()))
            info.addView(txt(date, 13, Pal.TEXT, bold = true))
            info.addView(txt("${f.length() / 1024} КБ · ${store.sourceOf(f)}", 11, Pal.MUTED))
            row.addView(info, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
            card.addView(row)
            card.setOnClickListener { openPhoto(f) }
            c.addView(card)
        }
        c.addView(txt("Снимки хранятся в приватной папке приложения. «Сохранить в галерею» — на экране снимка.", 11, Pal.MUTED))
        return c
    }

    // ---------- Вкладка «Консоль» ----------

    private fun buildConsoleTab(): View {
        val c = column()
        val cardTop = card()
        val target = consoleChar
        cardTop.addView(txt("Характеристика для команд", 12, Pal.MUTED, bold = true))
        cardTop.addView(
            txt(
                target?.let { GattNames.uuidLabel(it) } ?: "не выбрана",
                14,
                if (target != null) Pal.TEXT else Pal.MUTED,
                bold = target != null
            )
        )
        cardTop.addView(txt("Выберите её в GATT кнопкой «→ Консоль».", 11, Pal.MUTED))
        cardTop.addView(spacer(10))

        val field = input("01 FF 7A или text:привет", consoleDraft)
        field.addTextChangedListener(object : android.text.TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {
                consoleDraft = s?.toString() ?: ""
            }

            override fun afterTextChanged(s: android.text.Editable?) {}
        })
        cardTop.addView(field)

        val modes = row()
        modes.addView(pill("hex", !consoleTextMode) {
            consoleTextMode = false
            rebuild()
        })
        modes.addView(pill("текст", consoleTextMode) {
            consoleTextMode = true
            rebuild()
        })
        cardTop.addView(modes)
        cardTop.addView(spacer(8))

        val buttons = row()
        buttons.addView(actionButton("Отправить", primary = true) {
            sendConsole(field.text.toString())
        })
        buttons.addView(actionButton("Батарея", primary = false) { readBattery() })
        buttons.addView(actionButton("Сведения", primary = false) { readDeviceInfo() })
        cardTop.addView(buttons)
        c.addView(cardTop)

        val logCard = card()
        val logHead = row()
        logHead.addView(txt("Журнал", 12, Pal.MUTED, bold = true), LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        logHead.addView(pill("Очистить", false) {
            logs.clear()
            addLog("Журнал очищен")
            rebuild()
        })
        logCard.addView(logHead)
        logCard.addView(spacer(6))
        val logView = txt(
            if (logs.isEmpty()) "Здесь появятся события: подключение, чтение характеристик, ошибки." else logs.joinToString("\n"),
            10,
            Pal.MUTED,
            mono = true
        )
        val logScroll = ScrollView(this)
        logScroll.addView(logView)
        logCard.addView(logScroll, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(300)))
        c.addView(logCard)

        consoleLogView = logView
        consoleScroll = logScroll
        logScroll.post { logScroll.fullScroll(View.FOCUS_DOWN) }
        return c
    }

    private fun sendConsole(raw: String) {
        val char = consoleChar
        if (char == null) {
            toast("Сначала выберите характеристику в GATT")
            return
        }
        val payload = if (consoleTextMode) raw.toByteArray(Charsets.UTF_8) else try {
            parsePayload(raw)
        } catch (e: Exception) {
            toast("Hex с ошибкой: ${e.message}")
            return
        }
        addLog("← ${bytesToHex(payload)}")
        doWrite(consoleService, char, payload)
    }

    private fun readDeviceInfo() {
        if (DemoDevice.isDemo(connAddress)) {
            addLog("Демо: RayX Demo · прошивка 1.0.0-demo")
            return
        }
        val infoService = gattServices.firstOrNull { GattNames.shortCode(it.uuid) == 0x180A }?.uuid
        val chars = listOf(0x2A29, 0x2A24, 0x2A26, 0x2A25)
        var sent = false
        for (short in chars) {
            val ch = gattServices.flatMap { it.chars }.firstOrNull { GattNames.shortCode(it.uuid) == short }
            if (ch != null) {
                ble.read(infoService, ch.uuid)
                sent = true
            }
        }
        if (!sent) toast("Устройство не отдаёт Device Information")
    }

    // ---------- Диалоги ----------

    private fun showSheet(
        title: String,
        bodyView: View,
        okText: String? = null,
        onOk: (() -> Unit)? = null
    ): Dialog {
        val dialog = Dialog(this)
        val wrapper = column(16)
        wrapper.background = roundRect(Pal.SURFACE, 20, Pal.STROKE)
        wrapper.addView(txt(title, 17, Pal.TEXT, bold = true))
        wrapper.addView(spacer(10))
        val tall = bodyView is ScrollView
        if (tall) {
            wrapper.addView(
                bodyView,
                LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f)
            )
        } else {
            wrapper.addView(
                bodyView,
                LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT
                )
            )
        }
        if (okText != null) {
            wrapper.addView(spacer(10))
            val actions = row()
            actions.gravity = Gravity.END
            actions.addView(actionButton(okText, primary = true) {
                onOk?.invoke()
                dialog.dismiss()
            })
            wrapper.addView(actions)
        } else {
            wrapper.addView(spacer(8))
            wrapper.addView(pill("Закрыть", false) { dialog.dismiss() })
        }
        dialog.setContentView(wrapper)
        dialog.window?.setBackgroundDrawable(ColorDrawable(Color.TRANSPARENT))
        dialog.show()
        val width = (resources.displayMetrics.widthPixels * 0.92f).toInt()
        val height = if (tall) {
            (resources.displayMetrics.heightPixels * 0.86f).toInt()
        } else {
            LinearLayout.LayoutParams.WRAP_CONTENT
        }
        dialog.window?.setLayout(width, height)
        return dialog
    }

    private fun hintCard(
        title: String,
        text: String,
        buttonText: String? = null,
        action: (() -> Unit)? = null
    ): View {
        val card = card()
        card.addView(txt(title, 14, Pal.TEXT, bold = true))
        card.addView(spacer(6))
        card.addView(txt(text, 12, Pal.MUTED))
        if (buttonText != null) {
            card.addView(spacer(10))
            card.addView(actionButton(buttonText, primary = false) { action?.invoke() })
        }
        return card
    }

    private fun section(title: String): TextView {
        val t = txt(title, 12, Pal.MUTED, bold = true)
        t.setPadding(0, dp(10), 0, dp(6))
        return t
    }

    private fun label(title: String): TextView {
        val t = txt(title, 11, Pal.MUTED)
        t.setPadding(0, dp(10), 0, dp(4))
        return t
    }

    private fun capTitle(cap: String): String = when (cap) {
        "camera" -> "камера"
        "battery" -> "батарея"
        "device_info" -> "о устройстве"
        "sensors" -> "датчики"
        "audio" -> "звук"
        "display" -> "дисплей"
        else -> cap
    }

    private fun capColor(cap: String): Int = when (cap) {
        "camera" -> Pal.GREEN
        "battery" -> Pal.ACCENT
        "display" -> Pal.VIOLET
        "audio" -> Pal.AMBER
        else -> Pal.MUTED
    }

    // ---------- Фото и экспорт ----------

    private fun thumb(file: File, targetPx: Int): Bitmap? {
        return try {
            val bounds = BitmapFactory.Options()
            bounds.inJustDecodeBounds = true
            BitmapFactory.decodeFile(file.path, bounds)
            var sample = 1
            while (bounds.outWidth / (sample * 2) >= targetPx) sample *= 2
            BitmapFactory.decodeFile(file.path, BitmapFactory.Options().apply { inSampleSize = sample })
        } catch (e: Exception) {
            null
        }
    }

    private fun exportPhoto(file: File) {
        if (Build.VERSION.SDK_INT >= 29 || checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE) == PackageManager.PERMISSION_GRANTED) {
            val ok = store.exportToGallery(file)
            toast(if (ok) "Снимок в галерее: Pictures/BlueLink" else "Не удалось сохранить в галерею")
        } else {
            pendingGalleryExport = file
            requestPermissions(arrayOf(Manifest.permission.WRITE_EXTERNAL_STORAGE), REQ_WRITE_STORAGE)
        }
    }

    companion object {
        const val TAB_SCAN = "scan"
        const val TAB_DEVICE = "device"
        const val TAB_CAMERA = "camera"
        const val TAB_GATT = "gatt"
        const val TAB_PROFILES = "profiles"
        const val TAB_PHOTOS = "photos"
        const val TAB_CONSOLE = "console"

        private const val REQ_BLE = 100
        private const val REQ_ENABLE_BT = 101
        private const val REQ_WRITE_STORAGE = 102
        private const val REQ_WIFI = 103

        private val TABS = listOf(
            TAB_SCAN to "🔍 Поиск",
            TAB_DEVICE to "📱 Устройство",
            TAB_CAMERA to "📷 Камера",
            TAB_GATT to "🧩 GATT",
            TAB_PROFILES to "⚙️ Профили",
            TAB_PHOTOS to "🖼 Фото",
            TAB_CONSOLE to "⌨️ Консоль"
        )
    }
}

private fun shortOrFullUuid(uuid: UUID): String {
    val code = GattNames.shortCode(uuid)
    return if (code != null) String.format("%04x", code) else uuid.toString()
}

private fun ImageView.loadThumb(file: File, targetPx: Int) {
    try {
        val bounds = BitmapFactory.Options()
        bounds.inJustDecodeBounds = true
        BitmapFactory.decodeFile(file.path, bounds)
        var sample = 1
        while (bounds.outWidth / (sample * 2) >= targetPx) sample *= 2
        val bitmap = BitmapFactory.decodeFile(file.path, BitmapFactory.Options().apply { inSampleSize = sample })
        if (bitmap != null) setImageBitmap(bitmap)
    } catch (ignored: Exception) {
    }
}


