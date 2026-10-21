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
    private var batteryUnavailable = false
    private var lastConnItem: ScanItem? = null
    private var autoProfileFor = ""
    private var connError = ""
    private var cameraProfile: DeviceProfile? = null

    // Диагностика: всё, что реально пришло от устройства, чтобы можно было переслать отчётом.
    private val notifStats = HashMap<String, NotifStat>()
    private var sdpProfiles: List<UUID> = emptyList()
    private var crashText: String? = null
    private var auditStatus = ""
    private var auditor: DeviceAuditor? = null
    private var extraNotes = ArrayList<String>()

    // Очки: состояние панели, данные от устройства и служебные поля протокола.
    private var heyChannel = HeyCyan.CH_CTRL
    private var heyTypeText = "41"
    private var heyBattery: Int? = null
    private var heyModel: String? = null
    private var heyFirmware: String? = null
    private var heyLastResponse = ""
    private var heyActionStatus = ""
    private var heySendTitle = ""
    private var heyLastTx: ByteArray? = null
    private var heyLastTxAt = 0L
    private var heyAdvanced = false
    private var heyFilesOpen = false
    private var heyWifi: List<Pair<String, Int>> = emptyList()
    private var heyAutoDone = false
    private var heyCharging = false
    private var heyFiles = -1
    private var heyFilesRaw = ""
    private var heyStreamCount = 0
    private var heyStreamBytes = 0
    private var heyStreamLogged = 0

    // Съёмка: что очки реально ответили и как идёт приём миниатюры по Bluetooth.
    private val heyFramer = HeyCyan.BigFramer()
    private var heyGlassWork = -1
    private var heyGlassError = -1
    private var heyVideoOn = false
    private var heyAudioOn = false
    private var heyPhotos = -1
    private var heyVideos = -1
    private var heyRecords = -1
    private var heyExpectPhoto = false
    private var heyPhotoBaseline = -1
    // Приём миниатюры: очки присылают части не по порядку, поэтому складываем их по номеру.
    private val heyThumbParts = HashMap<Int, ByteArray>()
    private var heyThumbStartedAt = 0L
    private var heyThumbRounds = 0
    // Wi-Fi очков и выгрузка файлов.
    private var heyMedia: GlassesMedia? = null
    private var heyWifiSsid = ""
    private var heyWifiPass = ""
    private var heyP2pIp: String? = null
    private var heyTransferOn = false
    private var heyMediaStatus = ""
    private var heyMediaNames: List<String> = emptyList()
    private var heyMediaSaved = 0
    private var heyVideoLimit = -1
    private var heyPulse: Runnable? = null
    // Мы сами помним, что попросили запись: ответ очков о текущем режиме может
    // приходить с задержкой или говорить о другом режиме — «пульс» от этого не зависит.
    private var heyWantVideo = false
    private var heyWantAudio = false
    private var heyLastEventAt = 0L
    private var heyPhotoStatus = ""
    private var heyThumbTotal = -1
    private var heyPhotoBitmap: Bitmap? = null

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

    override fun attachBaseContext(newBase: Context) {
        super.attachBaseContext(newBase)
        // Стек падения сохраняем в файл: без этого на закрытых прошивках не понять, что произошло.
        try {
            val previous = Thread.getDefaultUncaughtExceptionHandler()
            Thread.setDefaultUncaughtExceptionHandler { thread, error ->
                try {
                    File(newBase.filesDir, "last_crash.txt").writeText(android.util.Log.getStackTraceString(error))
                } catch (ignored: Exception) {
                }
                previous?.uncaughtException(thread, error)
            }
        } catch (ignored: Exception) {
        }
    }

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

        crashText = try {
            val f = File(filesDir, "last_crash.txt")
            if (f.exists()) f.readText() else null
        } catch (e: Exception) {
            null
        }

        buildRoot()
        rebuild()
        addLog("BlueLink запущен, версия ${appVersion()}")
        crashText?.let { addLog("Прошлый запуск завершился ошибкой — стек в отчёте") }

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
        val reportBtn = txt("📋", 15, Pal.TEXT, bold = true)
        reportBtn.setPadding(dp(10), dp(4), dp(10), dp(4))
        reportBtn.background = roundRect(Pal.SURFACE, 999, Pal.STROKE)
        reportBtn.isClickable = true
        reportBtn.setOnClickListener {
            tab = TAB_REPORT
            rebuild()
        }
        val reportLp = LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.WRAP_CONTENT,
            LinearLayout.LayoutParams.WRAP_CONTENT
        )
        reportLp.rightMargin = dp(8)
        top.addView(reportBtn, reportLp)

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
        val keepScroll = lastBuiltTab == tab && tab == TAB_SCAN
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
            TAB_REPORT -> buildReportTab()
            TAB_HEY -> buildHeyTab()
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
        val version = appVersion()
        subtitle.text = when {
            connected -> "$connName · ${gattServices.size} сервисов · v$version"
            activeProfile != null -> "Профиль: ${activeProfile?.name} · v$version"
            else -> "Bluetooth-пульт для любых устройств · v$version"
        }
    }

    private fun appVersion(): String = try {
        packageManager.getPackageInfo(packageName, 0).versionName ?: "?"
    } catch (e: Exception) {
        "?"
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
            lastConnItem = item
            connError = ""
            autoProfileFor = ""
            cameraProfile = null
            val matched = profiles.bestFor(item)
            if (matched != null) {
                activeProfile = matched
                saveActiveProfile()
            }
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
        lastConnItem = DemoDevice.scanItem()
        connError = ""
        cameraProfile = null
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
        if (state == ConnState.DISCONNECTED) connError = ble.lastError
        if (name.isNotEmpty()) connName = name
        if (address.isNotEmpty() && state != ConnState.DISCONNECTED) connAddress = address
        if (state == ConnState.CONNECTING) {
            gattServices = emptyList()
            batteryPercent = null
            batteryAttempted = false
            heyAutoDone = false
            heyLastResponse = ""
            heyActionStatus = ""
        }
        if (state == ConnState.DISCONNECTED) {
            gattServices = emptyList()
            batteryPercent = null
            batteryAttempted = false
            subscribed.clear()
            heyFramer.reset()
            heyGlassWork = -1
            heyGlassError = -1
            heyVideoOn = false
            heyAudioOn = false
            heyThumbTotal = -1
            heyThumbParts.clear()
            heyStopPulse()
            heyWantVideo = false
            heyWantAudio = false
            heyTransferOn = false
            heyMedia?.cancel()
            heyMedia = null
            heyWifiSsid = ""
            heyWifiPass = ""
            if (DemoDevice.isDemo(address)) connAddress = ""
        }
        rebuild()
    }

    override fun onServices(services: List<GattServiceInfo>) {
        gattServices = services
        batteryUnavailable = false
        if (services.isNotEmpty()) ensureProfileMatchesDevice()
        syncBattery()
        if (heyAvailable() && connState == ConnState.CONNECTED && !heyAutoDone) {
            // Очки HeyCyan: сразу подписываемся на их каналы и читаем паспорт устройства,
            // иначе интерфейс остаётся без данных до первого нажатия.
            heyAutoDone = true
            ui.postDelayed({ heySubscribeProtocol() }, 300)
            ui.postDelayed({ heyReadIdentity() }, 2600)
            // Прошлая сессия могла оставить очки в режиме передачи файлов — в нём камера
            // занята, и команды съёмки формально принимаются, но ничего не происходит.
            ui.postDelayed({
                heySend(
                    HeyCyan.CH_SERIAL, 0x41, HeyCyan.control(HeyCyan.Work.TRANSFER_STOP),
                    "Проверка режима: выхожу из передачи"
                )
            }, 5200)
        }
        rebuild()
    }

    private fun heyReadIdentity() {
        if (connState != ConnState.CONNECTED) return
        val info = UUID.fromString("0000180a-0000-1000-8000-00805f9b34fb")
        for (code in listOf(0x2A26, 0x2A27, 0x2A25)) {
            val char = gattServices.firstOrNull { it.uuid == info }
                ?.chars?.firstOrNull { GattNames.shortCode(it.uuid) == code }
            if (char != null && char.readable) ble.read(info, char.uuid)
        }
        heyRefresh()
    }

    /**
     * Если подходящего профиля нет — собираем его из того, что реально отдаёт устройство:
     * батарея, Device Information, а также кандидаты на камеру (запись + уведомления в сервисе).
     */
    private fun ensureProfileMatchesDevice() {
        val item = scanItems.firstOrNull { it.address == connAddress } ?: lastConnItem
        val matched = item?.let { profiles.bestFor(it) }
            ?: profiles.ensureLoaded().firstOrNull {
                it.namePrefixes.any { p -> p.isNotBlank() && connName.lowercase().contains(p.lowercase()) }
            }
        if (matched != null) {
            if (activeProfile == null || activeProfile?.auto == true) {
                activeProfile = matched
                saveActiveProfile()
                addLog("Профиль найден: ${matched.name}")
            }
            return
        }
        if (autoProfileFor == connAddress) return
        val auto = buildAutoProfile() ?: return
        autoProfileFor = connAddress
        profiles.saveUser(auto)
        activeProfile = auto
        saveActiveProfile()
        addLog("Создан авто-профиль: ${auto.name}")
        toast("Профиль создан автоматически по данным GATT")
    }

    private fun buildAutoProfile(): DeviceProfile? {
        if (gattServices.isEmpty()) return null
        var batteryService: UUID? = null
        var batteryChar: UUID? = null
        val caps = LinkedHashSet<String>()
        caps.add("device_info")

        for (svc in gattServices) {
            for (ch in svc.chars) {
                if (GattNames.shortCode(ch.uuid) == 0x2A19 && batteryChar == null) {
                    batteryChar = ch.uuid
                    batteryService = svc.uuid
                }
            }
        }
        if (batteryChar != null) caps.add("battery")

        // Кандидаты на камеру: сервис производителя, где есть и запись, и уведомления.
        val candidates = ArrayList<CameraSpec>()
        for (svc in gattServices) {
            val vendor = GattNames.shortCode(svc.uuid) == null ||
                (GattNames.shortCode(svc.uuid) ?: 0) >= 0xFF00
            if (!vendor) continue
            val writeChar = svc.chars.firstOrNull { it.writable }
            val notifyChar = svc.chars.firstOrNull { it.notifiable && it.uuid != writeChar?.uuid }
            if (writeChar != null && notifyChar != null) {
                candidates.add(
                    CameraSpec(
                        mode = "ble",
                        label = "Проверить камеру",
                        service = svc.uuid,
                        triggerChar = writeChar.uuid,
                        dataChar = notifyChar.uuid,
                        trigger = byteArrayOf(0x01),
                        framing = "jpeg"
                    )
                )
                caps.add("camera")
            }
        }

        val deviceName = connName.ifBlank { "Устройство ${connAddress.takeLast(5)}" }
        val prefix = deviceName.substringBefore(" (").trim()
        val notes = ArrayList<String>()
        if (batteryChar != null) {
            notes.add("Батарея: ${GattNames.uuidLabel(batteryChar)} (найдена автоматически)")
        } else {
            notes.add("Устройство не сообщает уровень заряда по стандартной характеристике.")
        }
        if (candidates.isNotEmpty()) {
            notes.add("Возможная камера найдена в GATT — нажмите «Проверить камеру» в карточке устройства.")
        } else {
            notes.add("Явной камеры в GATT нет: возможно, устройство отдаёт фото только через своё приложение.")
        }
        notes.add("Сервисов: ${gattServices.size}, характеристик: ${gattServices.sumOf { it.chars.size }}")

        return DeviceProfile(
            id = "auto_" + connAddress.replace(Regex("[^a-zA-Z0-9]"), "").ifBlank { System.currentTimeMillis().toString(16) },
            name = "$deviceName (авто)",
            vendor = "определено автоматически",
            description = "Профиль собран по данным GATT этого устройства. Его можно поправить в редакторе.",
            namePrefixes = if (prefix.isNotBlank()) listOf(prefix) else emptyList(),
            serviceUuids = gattServices.map { it.uuid }.take(6),
            capabilities = caps.toList(),
            batteryService = batteryService,
            batteryChar = batteryChar,
            camera = null,
            notes = notes,
            auto = true,
            cameraCandidates = candidates
        )
    }

    /**
     * Ищет характеристику заряда: сначала в профиле, потом стандартную 0x2A19 в любом сервисе.
     * Если она поддерживает уведомления — подписывается, чтобы процент обновлялся сам.
     */
    private fun batteryRef(): Pair<GattServiceInfo, GattCharInfo>? {
        val profile = activeProfile
        val wanted = profile?.batteryChar
        if (wanted != null) {
            for (svc in gattServices) {
                svc.chars.firstOrNull { it.uuid == wanted }?.let { return svc to it }
            }
        }
        for (svc in gattServices) {
            for (ch in svc.chars) {
                if (GattNames.shortCode(ch.uuid) == 0x2A19) return svc to ch
            }
        }
        return null
    }

    private fun syncBattery(force: Boolean = false) {
        if (DemoDevice.isDemo(connAddress)) {
            batteryPercent = 78
            return
        }
        if (!force && batteryAttempted) return
        val ref = batteryRef()
        if (ref == null) {
            batteryUnavailable = true
            return
        }
        batteryUnavailable = false
        batteryAttempted = true
        val (svc, ch) = ref
        if (ch.notifiable) {
            val key = "${svc.uuid}|${ch.uuid}"
            if (subscribed.add(key)) ble.subscribe(svc.uuid, ch.uuid, true)
        }
        if (ch.readable) {
            ble.read(svc.uuid, ch.uuid)
        } else if (!ch.notifiable) {
            batteryUnavailable = true
        }
    }

    override fun onCharValue(service: UUID, char: UUID, value: ByteArray) {
        val stat = notifStats.getOrPut("$service|$char") { NotifStat() }
        stat.count += 1
        stat.bytes += value.size
        if (stat.first == null) stat.first = value.take(40).toByteArray()
        stat.last = value.take(40).toByteArray()
        stat.lastAt = System.currentTimeMillis()

        camera.feed(service, char, value)
        val isBatteryChar = GattNames.shortCode(char) == 0x2A19 || activeProfile?.batteryChar == char
        if (isBatteryChar && value.isNotEmpty()) {
            batteryPercent = value[0].toInt() and 0xFF
            batteryUnavailable = false
        }
        // Во время передачи снимка уведомления идут потоком: журнал не засоряем и экран не дёргаем.
        if (camera.isCapturing()) return
        val short = GattNames.shortCode(char)
        if (short == 0x2A26) heyFirmware = String(value, Charsets.UTF_8).trim().ifBlank { null }
        if (short == 0x2A27) heyModel = String(value, Charsets.UTF_8).trim().ifBlank { null }
        if (short == 0x2A00 && heyModel.isNullOrBlank()) heyModel = String(value, Charsets.UTF_8).trim()
        val protocolFrame = heyObserve(value)
        when (GattNames.shortCode(char)) {
            0x2A26 -> String(value, Charsets.UTF_8).trim().ifBlank { null }?.let { heyFirmware = it }
            0x2A27 -> String(value, Charsets.UTF_8).trim().ifBlank { null }?.let { heyModel = it }
        }
        // Кадры протокола уже разобраны по смыслу: в журнал их простым текстом не дублируем.
        if (protocolFrame) {
            if (tab == TAB_GATT || tab == TAB_DEVICE || tab == TAB_HEY) rebuildThrottled()
            return
        }
        val text = heyLastResponse.ifBlank {
            GattNames.describe(char, value) ?: bytesToHex(value.take(24).toByteArray())
        }
        addLog("→ ${GattNames.charName(char)}: $text")
        if (tab == TAB_GATT || tab == TAB_DEVICE || tab == TAB_HEY) rebuildThrottled()
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
            if (tab == TAB_CAMERA || tab == TAB_DEVICE || tab == TAB_HEY) rebuild()
        }
    }

    override fun onPhoto(file: File, bytes: ByteArray, source: String) {
        ui.post {
            lastPhoto = file
            lastPhotoBitmap = thumb(file, 320)
            addLog("Снимок сохранён: ${file.name} (${bytes.size / 1024} КБ)")
            if (tab == TAB_CAMERA || tab == TAB_PHOTOS || tab == TAB_DEVICE || tab == TAB_HEY) rebuild()
        }
    }

    override fun onCameraLog(line: String) {
        ui.post { addLog(line) }
    }

    private fun captureWith(profile: DeviceProfile?, persist: Boolean = true) {
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
        cameraProfile = profile
        if (persist) {
            activeProfile = profile
            saveActiveProfile()
        }
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
        if (item.classic) tags.addView(badge("сопряжено · классический BT", Pal.AMBER))
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
        val demo = DemoDevice.isDemo(connAddress)
        val info = card()
        val head = row()
        head.addView(txt(connName, 16, Pal.TEXT, bold = true), LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        head.addView(
            badge(
                when (connState) {
                    ConnState.CONNECTED -> "на связи"
                    ConnState.CONNECTING -> "соединение…"
                    else -> "нет связи"
                },
                when (connState) {
                    ConnState.CONNECTED -> Pal.GREEN
                    ConnState.CONNECTING -> Pal.AMBER
                    else -> Pal.RED
                }
            )
        )
        info.addView(head)
        info.addView(txt(connAddress, 11, Pal.MUTED, mono = true))
        info.addView(spacer(8))
        val meta = row()
        meta.addView(badge("сервисов: ${gattServices.size}", Pal.ACCENT))
        if (ble.transportLabel.isNotBlank()) meta.addView(badge("транспорт ${ble.transportLabel}", Pal.MUTED))
        if (connected) meta.addView(badge("MTU ${ble.mtu}", Pal.MUTED))
        if (demo) meta.addView(badge("демо", Pal.VIOLET))
        info.addView(meta)

        if (connError.isNotBlank() && !connected) {
            info.addView(spacer(8))
            info.addView(txt(connError, 12, Pal.AMBER))
        }

        info.addView(spacer(10))
        val buttons = row()
        if (connected) {
            buttons.addView(actionButton("Отключить", primary = false) { doDisconnect() })
            if (!demo) buttons.addView(actionButton("Переподключиться", primary = false) {
                connError = ""
                batteryAttempted = false
                batteryUnavailable = false
                subscribed.clear()
                ble.reconnect()
                rebuild()
            })
        } else {
            buttons.addView(actionButton("Подключиться снова", primary = true) {
                val item = lastConnItem
                if (item != null) connectTo(item) else {
                    tab = TAB_SCAN
                    rebuild()
                }
            })
        }
        buttons.addView(actionButton("Все сервисы", primary = connected && gattServices.isEmpty()) {
            tab = TAB_GATT
            rebuild()
        })
        info.addView(buttons)
        c.addView(info)

        if (heyAvailable()) {
            val heyCard = card()
            heyCard.addView(txt("🕶 Это очки с готовыми действиями", 13, Pal.TEXT, bold = true))
            heyCard.addView(
                txt(
                    "Фото, видео, голос, помощник и файлы — на вкладке «Очки». Там же заряд и данные устройства.",
                    11,
                    Pal.MUTED
                )
            )
            heyCard.addView(spacer(8))
            val heyRow = row()
            heyRow.addView(actionButton("Открыть панель очков", primary = true) {
                tab = TAB_HEY
                rebuild()
            })
            heyCard.addView(heyRow)
            if (heyBattery == null) {
                heyCard.addView(spacer(6))
                heyCard.addView(txt("Заряд: очки пока не сообщают его по Bluetooth", 11, Pal.AMBER))
            }
            c.addView(heyCard)
        }

        // Почему не подключается: отдельная понятная карточка для классических устройств.
        if (!connected && lastConnItem?.classic == true) {
            val classicCard = card()
            classicCard.addView(txt("Похоже, это классический Bluetooth", 14, Pal.TEXT, bold = true))
            classicCard.addView(spacer(6))
            classicCard.addView(
                txt(
                    "Наушники, колонки и гарнитуры часто работают только по классическому профилю " +
                        "(A2DP/HFP) и не отдают данные через GATT — тот канал, с которым работает BlueLink. " +
                        "Соединение при этом уже есть на уровне системы: звук идёт, а характеристик для чтения нет. " +
                        "Заряд таких наушников Android показывает в своих настройках Bluetooth.",
                    12,
                    Pal.MUTED
                )
            )
            classicCard.addView(spacer(10))
            classicCard.addView(actionButton("Настройки Bluetooth", primary = false) {
                openBluetoothSettings()
            })
            c.addView(classicCard)
        }

        // Батарея: показываем честно — есть характеристика или нет.
        val battery = card()
        val rowB = row()
        rowB.addView(txt("🔋", 22))
        rowB.addView(hspace(10))
        // У очков нет стандартной характеристики заряда: число приходит по их протоколу.
        val percent = batteryPercent ?: heyBattery
        rowB.addView(
            txt(
                when {
                    percent != null -> "$percent%"
                    batteryUnavailable || (connected && gattServices.isNotEmpty()) -> "—"
                    else -> "…"
                },
                24,
                if (percent != null) Pal.GREEN else Pal.MUTED,
                bold = true
            )
        )
        rowB.addView(hspace(10))
        val box = column()
        box.addView(txt("Батарея устройства", 13, Pal.TEXT))
        box.addView(
            txt(
                when {
                    demo -> "демо-значение"
                    batteryRef() != null -> "характеристика Battery Level найдена"
                    connected -> "устройство не сообщает заряд"
                    else -> "появится после подключения"
                },
                11,
                Pal.MUTED
            )
        )
        rowB.addView(box, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        rowB.addView(pill("Обновить", false) { readBattery() })
        battery.addView(rowB)
        if (connected && batteryRef() == null && !demo) {
            battery.addView(spacer(8))
            battery.addView(
                txt(
                    "Здесь нет стандартной характеристики 0x2A19. У наушников заряд обычно виден в настройках Bluetooth, у остальных устройств его может не быть вовсе.",
                    11,
                    Pal.MUTED
                )
            )
        }
        c.addView(battery)

        if (connected && gattServices.isEmpty() && !demo) {
            val emptyCard = card()
            emptyCard.addView(txt("Устройство не отдало сервисы", 14, Pal.TEXT, bold = true))
            emptyCard.addView(spacer(6))
            emptyCard.addView(
                txt(
                    "Соединение установлено, но список характеристик пуст. У классических наушников и колонок " +
                        "GATT-данных обычно нет совсем — это не ошибка приложения. Если устройство всё-таки BLE, " +
                        "попробуйте переподключиться: часть устройств отдаёт таблицу только со второй попытки.",
                    12,
                    Pal.MUTED
                )
            )
            emptyCard.addView(spacer(10))
            val emptyActions = row()
            emptyActions.addView(actionButton("Переподключиться", primary = true) {
                connError = ""
                batteryAttempted = false
                batteryUnavailable = false
                subscribed.clear()
                ble.reconnect()
                rebuild()
            })
            emptyActions.addView(actionButton("Журнал", primary = false) { copyLog() })
            emptyCard.addView(emptyActions)
            emptyCard.addView(spacer(6))
            emptyCard.addView(actionButton("Настройки Bluetooth", primary = false) {
                openBluetoothSettings()
            })
            c.addView(emptyCard)
        }

        // Профиль (в т.ч. автоматически собранный)
        val profile = activeProfile
        if (profile != null) {
            val p = card()
            val ph = row()
            ph.addView(txt("Профиль устройства", 12, Pal.MUTED, bold = true), LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
            if (profile.auto) ph.addView(badge("авто", Pal.AMBER))
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
            if (profile.cameraCandidates.isNotEmpty()) {
                p.addView(spacer(10))
                p.addView(txt("Камера в GATT: найдено ${profile.cameraCandidates.size} вариант(а) — можно проверить, не настраивая профиль вручную.", 11, Pal.MUTED))
                for (cand in profile.cameraCandidates.take(3)) {
                    p.addView(spacer(6))
                    val candText = "${GattNames.uuidLabel(cand.triggerChar ?: UUID(0L, 0L))} → ${GattNames.uuidLabel(cand.dataChar ?: UUID(0L, 0L))}"
                    p.addView(txt(candText, 10, Pal.MUTED, mono = true))
                    val rowC = row()
                    rowC.addView(actionButton("Проверить камеру", primary = true) {
                        val testProfile = profile.copy(
                            id = profile.id + "_test",
                            camera = cand.copy(label = "Проверить камеру")
                        )
                        captureWith(testProfile, persist = false)
                    })
                    rowC.addView(pill("В профиль", false) {
                        openEditor(profile, cand)
                    })
                    p.addView(rowC)
                }
            }
            if (profile.notes.isNotEmpty()) {
                p.addView(spacer(8))
                for (note in profile.notes) p.addView(txt("· $note", 11, Pal.MUTED))
            }
            p.addView(spacer(10))
            val pActions = row()
            pActions.addView(pill("Изменить", false) { openEditor(profile) })
            pActions.addView(pill("Все профили", false) {
                tab = TAB_PROFILES
                rebuild()
            })
            p.addView(pActions)
            c.addView(p)
        } else if (connected && gattServices.isNotEmpty()) {
            c.addView(hintCard("Профиль не собран", "Сервисы получены, но профиль создать не удалось. Откройте «GATT» и посмотрите характеристики вручную."))
        }

        c.addView(
            actionButton("📋 Отчёт: скопировать всё, что узнали", primary = false) {
                tab = TAB_REPORT
                rebuild()
            }
        )

        c.addView(
            hintCard(
                "Что дальше",
                "Вкладка «GATT» показывает всё, что умеет устройство: батарею, датчики, кнопки, камеру. " +
                    "Рядом с характеристикой есть кнопки «Читать», «Писать», «Слушать» и «→ Камера»."
            )
        )
        return c
    }

    private fun openBluetoothSettings() {
        try {
            startActivity(Intent(Settings.ACTION_BLUETOOTH_SETTINGS))
        } catch (e: Exception) {
            toast("Не удалось открыть настройки Bluetooth")
        }
    }

    private fun readBattery() {
        if (DemoDevice.isDemo(connAddress)) {
            batteryPercent = 78
            rebuild()
            return
        }
        val ref = batteryRef()
        if (ref == null) {
            batteryUnavailable = true
            toast("Это устройство не сообщает уровень батареи")
            rebuild()
            return
        }
        val (svc, ch) = ref
        if (ch.notifiable) ble.subscribe(svc.uuid, ch.uuid, true)
        if (ch.readable) ble.read(svc.uuid, ch.uuid) else toast("Заряд можно только слушать (без чтения)")
    }

    // ---------- Вкладка «Камера» ----------

    private fun buildCameraTab(): View {
        val c = column()
        val profile = cameraProfile ?: activeProfile ?: profiles.byId("demo_glasses")

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
        c.addView(txt("сервисов: ${gattServices.size} · характеристик: ${gattServices.sumOf { it.chars.size }} · v${appVersion()}", 11, Pal.MUTED))

        if (gattServices.isEmpty()) {
            val connected = connState == ConnState.CONNECTED
            c.addView(
                hintCard(
                    if (connected) "Устройство не отдало сервисы" else "Список пуст",
                    when {
                        connected -> "Соединение есть, но GATT-таблица не пришла. Обычно помогает переподключение: часть устройств отдаёт сервисы только со второй попытки."
                        connError.isNotBlank() -> connError
                        lastConnItem?.classic == true -> "Похоже, это устройство классического Bluetooth (наушники, колонка). Такие устройства обычно не отдают GATT-данные — только звук через систему."
                        else -> "Подключитесь к устройству — сервисы появятся здесь автоматически."
                    }
                )
            )
            if (connected && !DemoDevice.isDemo(connAddress)) {
                c.addView(actionButton("Переподключиться", primary = true) {
                    connError = ""
                    batteryAttempted = false
                    batteryUnavailable = false
                    subscribed.clear()
                    ble.reconnect()
                    rebuild()
                })
            }
            c.addView(spacer(6))
            val emptyButtons = row()
            emptyButtons.addView(actionButton("К поиску устройств", primary = false) {
                tab = TAB_SCAN
                rebuild()
            })
            emptyButtons.addView(actionButton("Копировать журнал", primary = false) { copyLog() })
            c.addView(emptyButtons)
            c.addView(spacer(8))
            c.addView(
                listOf(
                    "Подключение: ${if (connState == ConnState.CONNECTED) "есть" else "нет"}",
                    "Транспорт: ${ble.transportLabel.ifBlank { "—" }}",
                    "MTU: ${ble.mtu}",
                    "Сервисов: ${gattServices.size}",
                    "Устройство: $connName ($connAddress)",
                    "Версия приложения: v${appVersion()}"
                ).joinToString("\n").let { txt(it, 11, Pal.MUTED, mono = true) }
            )
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
        val vendorService = GattNames.shortCode(service) == null || (GattNames.shortCode(service) ?: 0) >= 0xFF00
        if (vendorService && ch.writable) {
            actions.addView(pill("→ Команда камеры", false) {
                val notifyChar = gattServices.firstOrNull { it.uuid == service }
                    ?.chars?.firstOrNull { it.notifiable && it.uuid != ch.uuid }?.uuid
                openEditor(
                    activeProfile,
                    CameraSpec(
                        mode = "ble",
                        label = "Снять фото",
                        service = service,
                        triggerChar = ch.uuid,
                        dataChar = notifyChar,
                        trigger = byteArrayOf(0x01),
                        framing = "jpeg"
                    )
                )
            })
        }
        if (vendorService && ch.notifiable) {
            actions.addView(pill("→ Данные камеры", false) {
                openEditor(
                    activeProfile,
                    CameraSpec(
                        mode = "ble",
                        label = "Снять фото",
                        service = service,
                        triggerChar = null,
                        dataChar = ch.uuid,
                        trigger = byteArrayOf(0x01),
                        framing = "jpeg"
                    )
                )
            })
        }
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

    private fun copyLog() {
        if (logs.isEmpty()) {
            toast("Журнал пуст")
            return
        }
        val header = "BlueLink v${appVersion()} · устройство: $connName ($connAddress) · " +
            "транспорт ${ble.transportLabel.ifBlank { "—" }} · сервисов ${gattServices.size}\n"
        copyToClipboard(header + logs.joinToString("\n"))
        toast("Журнал скопирован")
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

    private fun openEditor(existing: DeviceProfile?, seed: CameraSpec? = null) {
        val isCopy = existing?.builtIn == true
        val base = existing
        val preset = seed ?: base?.camera
        val body = column()
        var mode = preset?.mode ?: "none"

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
        val cameraLabel = input("Снять фото", preset?.label ?: "Снять фото")
        body.addView(cameraLabel)

        body.addView(label("Камера: UUID сервиса"))
        val cameraService = input("ffe0", preset?.service?.let { shortOrFullUuid(it) } ?: "")
        body.addView(cameraService)

        body.addView(label("Камера: характеристика-триггер (для BLE)"))
        val triggerChar = input("ffe1", preset?.triggerChar?.let { shortOrFullUuid(it) } ?: "")
        body.addView(triggerChar)

        body.addView(label("Камера: характеристика данных (для BLE)"))
        val dataChar = input("ffe2", preset?.dataChar?.let { shortOrFullUuid(it) } ?: "")
        body.addView(dataChar)

        body.addView(label("Команда съёмки, hex"))
        val trigger = input("01", preset?.let { bytesToHex(it.trigger) } ?: "01")
        body.addView(trigger)

        body.addView(label("Формат потока: jpeg или sizeHeader"))
        val framing = input("jpeg", preset?.framing ?: "jpeg")
        body.addView(framing)

        body.addView(label("Wi-Fi: адрес снимка (для HTTP)"))
        val httpUrl = input("http://192.168.4.1/photo.jpg", preset?.httpUrl ?: "")
        body.addView(httpUrl)

        body.addView(label("Wi-Fi: имя сети очков"))
        val wifiSsid = input("GlassCam", preset?.wifiSsid ?: "")
        body.addView(wifiSsid)

        body.addView(label("Wi-Fi: пароль"))
        val wifiPass = input("12345678", preset?.wifiPassword ?: "")
        body.addView(wifiPass)

        body.addView(label("Пауза перед скачиванием, мс"))
        val waitMs = input("1200", (preset?.waitMs ?: 1200).toString())
        body.addView(waitMs)

        val scroll = ScrollView(this)
        scroll.addView(body)

        showSheet(if (existing == null) "Новый профиль" else "Профиль: ${existing.name}", scroll, "Сохранить") {
            val profileName = name.text.toString().trim()
            if (profileName.isEmpty()) {
                toast("Нужно название профиля")
                return@showSheet
            }
            val id = if (existing == null || isCopy || existing.builtIn) profiles.nextUserId() else existing.id
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
                builtIn = false,
                auto = false,
                cameraCandidates = emptyList()
            )
            profiles.saveUser(profile)
            activeProfile = profile
            saveActiveProfile()
            addLog("Профиль сохранён: ${profile.name}")
            toast("Профиль сохранён")
            rebuild()
        }
    }

    // ---------- Вкладка «Отчёт» ----------

    private fun buildReportTab(): View {
        val c = column()

        val head = row()
        head.addView(txt("Отчёт о диагностике", 16, Pal.TEXT, bold = true), LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        head.addView(pill("Обновить", false) { rebuild() })
        c.addView(head)
        c.addView(
            txt(
                "Здесь собрано всё, что приложение реально получило от устройства: сервисы, характеристики, " +
                    "значения, коды ошибок, пакеты, SDP-каналы и журнал. Нажмите «Копировать» и пришлите текст.",
                12,
                Pal.MUTED
            )
        )
        c.addView(spacer(10))

        val statusCard = card()
        statusCard.addView(txt("Состояние", 12, Pal.MUTED, bold = true))
        statusCard.addView(spacer(6))
        statusCard.addView(
            txt(
                buildString {
                    appendLine("Устройство: ${connName.ifBlank { "—" }}")
                    appendLine("Адрес: ${connAddress.ifBlank { "—" }}")
                    appendLine("Связь: ${when (connState) { ConnState.CONNECTED -> "есть"; ConnState.CONNECTING -> "подключается"; else -> "нет" }}")
                    appendLine("Транспорт: ${ble.transportLabel.ifBlank { "—" }} · MTU ${ble.mtu}")
                    appendLine("Сервисов: ${gattServices.size} · характеристик: ${gattServices.sumOf { it.chars.size }}")
                    appendLine("Пакетов от устройства: ${notifStats.values.sumOf { it.count }}")
                    appendLine("Сопряжение: ${ble.bondStateText()}")
                    append("SDP-профилей: ${sdpProfiles.size}")
                },
                11,
                Pal.TEXT,
                mono = true
            )
        )
        statusCard.addView(spacer(10))
        val actions = row()
        actions.addView(actionButton("Проверить всё", primary = true) { runAudit() })
        actions.addView(actionButton("Копировать", primary = false) { copyReport() })
        statusCard.addView(actions)
        val actions2 = row()
        actions2.addView(actionButton("SDP-каналы", primary = false) { fetchSdp() })
        actions2.addView(actionButton("Сопряжение", primary = false) {
            if (ble.createBond()) {
                Toast.makeText(this, "Подтвердите сопряжение в системном окне", Toast.LENGTH_LONG).show()
            } else {
                toast("Не удалось запустить сопряжение")
            }
        })
        statusCard.addView(actions2)
        val actions3 = row()
        actions3.addView(actionButton("Поделиться", primary = false) { shareReport() })
        actions3.addView(actionButton("На диск", primary = false) { saveReportFile() })
        statusCard.addView(actions3)
        if (auditStatus.isNotBlank()) {
            statusCard.addView(spacer(8))
            statusCard.addView(txt(auditStatus, 11, Pal.AMBER))
        }
        c.addView(statusCard)

        if (crashText != null) {
            c.addView(
                hintCard(
                    "Прошлый запуск завершился ошибкой",
                    "Стек падения включён в отчёт ниже. Это важная информация — пришлите её вместе с отчётом.",
                    "Забыть",
                ) {
                    crashText = null
                    try {
                        File(filesDir, "last_crash.txt").delete()
                    } catch (ignored: Exception) {
                    }
                    rebuild()
                }
            )
        }

        val text = buildReport()
        val preview = txt(text, 9, Pal.MUTED, mono = true)
        preview.setTextIsSelectable(true)
        val scroll = ScrollView(this)
        scroll.addView(preview)
        val cardText = card(10)
        cardText.addView(txt("Текст отчёта", 12, Pal.MUTED, bold = true))
        cardText.addView(spacer(6))
        cardText.addView(scroll, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(300)))
        c.addView(cardText)

        return c
    }

    private fun buildReport(): String = Report.build(
        ReportInputs(
            ctx = this,
            appVersion = "${appVersion()} (${appVersionCode()})",
            connName = connName,
            connAddress = connAddress,
            connState = when (connState) {
                ConnState.CONNECTED -> "CONNECTED"
                ConnState.CONNECTING -> "CONNECTING"
                ConnState.DISCONNECTED -> "DISCONNECTED"
                ConnState.IDLE -> "IDLE"
            },
            transport = ble.transportLabel,
            mtu = ble.mtu,
            services = gattServices,
            opStatus = ble.opStatus,
            notifStats = notifStats,
            logs = logs.toList(),
            scanItem = scanItems.firstOrNull { it.address == connAddress } ?: lastConnItem,
            bondText = ble.bondStateText() + if (connAddress.isNotBlank() && !DemoDevice.isDemo(connAddress)) "" else "",
            sdpProfiles = sdpProfiles,
            crash = crashText,
            extraNotes = extraNotes.toList()
        )
    )

    private fun appVersionCode(): Int = try {
        @Suppress("DEPRECATION")
        packageManager.getPackageInfo(packageName, 0).versionCode
    } catch (e: Exception) {
        0
    }

    private fun copyReport() {
        copyToClipboard(buildReport())
        toast("Отчёт скопирован — можно вставлять в чат")
    }

    private fun saveReportFile() {
        val file = Report.saveToFile(this, buildReport())
        if (file == null) {
            toast("Не удалось сохранить отчёт")
        } else {
            toast("Отчёт сохранён: ${file.name}")
        }
    }

    private fun shareReport() {
        try {
            val text = buildReport()
            val file = Report.saveToFile(this, text)
            val intent = if (file != null) {
                val uri = androidx.core.content.FileProvider.getUriForFile(
                    this, "$packageName.fileprovider", file
                )
                Intent(Intent.ACTION_SEND).apply {
                    type = "text/plain"
                    putExtra(Intent.EXTRA_STREAM, uri)
                    putExtra(Intent.EXTRA_TEXT, text)
                    addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                }
            } else {
                Intent(Intent.ACTION_SEND).apply {
                    type = "text/plain"
                    putExtra(Intent.EXTRA_TEXT, text)
                }
            }
            startActivity(Intent.createChooser(intent, "Отправить отчёт"))
        } catch (e: Exception) {
            copyReport()
        }
    }

    private fun runAudit() {
        if (DemoDevice.isDemo(connAddress)) {
            toast("Для демо-очков обход не нужен")
            return
        }
        if (connState != ConnState.CONNECTED) {
            toast("Сначала подключитесь к устройству")
            return
        }
        val existing = auditor
        if (existing != null && existing.isRunning()) {
            existing.stop()
            auditStatus = "Обход остановлен"
            rebuild()
            return
        }
        extraNotes.clear()
        extraNotes.add("Выполнен автоматический обход: чтение всех характеристик и подписка на уведомления.")
        val runner = DeviceAuditor(
            ble,
            onStep = { step ->
                ui.post {
                    auditStatus = step
                    if (tab == TAB_REPORT) rebuild()
                }
            },
            onDone = { done ->
                ui.post {
                    auditStatus = done
                    addLog("Обход: $done")
                    if (tab == TAB_REPORT) rebuild()
                }
            }
        )
        auditor = runner
        auditStatus = "Начинаю обход устройства…"
        rebuild()
        runner.start()
    }

    private fun fetchSdp() {
        if (DemoDevice.isDemo(connAddress)) {
            toast("Для демо-очков SDP не нужен")
            return
        }
        if (connState != ConnState.CONNECTED) {
            toast("Сначала подключитесь к устройству")
            return
        }
        auditStatus = "Запрашиваю SDP-профили…"
        rebuild()
        ble.fetchSdpProfiles { list ->
            ui.post {
                sdpProfiles = list
                auditStatus = if (list.isEmpty()) {
                    "SDP: устройство не объявило профилей"
                } else {
                    "SDP: найдено профилей ${list.size}"
                }
                addLog("SDP: ${list.size} профилей")
                if (tab == TAB_REPORT) rebuild()
            }
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

    // ---------- Очки: понятная панель действий ----------

    private fun heyAvailable(): Boolean =
        gattServices.any { it.uuid == HeyCyan.CTRL_SERVICE || it.uuid == HeyCyan.SERIAL_SERVICE }

    private fun heyTile(icon: String, title: String, hint: String, onClick: () -> Unit): View {
        val box = column()
        box.background = tappable(Pal.SURFACE_2, 14, Pal.STROKE)
        box.setPadding(dp(12), dp(12), dp(12), dp(12))
        box.isClickable = true
        box.isFocusable = true
        box.addView(txt("$icon  $title", 14, Pal.TEXT, bold = true))
        box.addView(txt(hint, 11, Pal.MUTED))
        box.setOnClickListener { onClick() }
        val lp = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
        lp.rightMargin = dp(8)
        lp.bottomMargin = dp(8)
        box.layoutParams = lp
        return box
    }

    private fun buildHeyTab(): View {
        val c = column()
        val connected = connState == ConnState.CONNECTED

        val head = row()
        head.addView(
            txt(if (isHeyCyanDevice()) "🕶 Очки ${connName.ifBlank { "" }}".trim() else "🕶 Очки", 16, Pal.TEXT, bold = true),
            LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
        )
        head.addView(
            badge(
                if (connected) "на связи" else "нет связи",
                if (connected) Pal.GREEN else Pal.RED
            )
        )
        c.addView(head)
        c.addView(
            txt(
                "Готовые действия — без байтов и команд. Просто нажмите, что нужно сделать.",
                12,
                Pal.MUTED
            )
        )
        c.addView(spacer(10))

        // Что известно об очках
        val state = card()
        state.addView(txt("Очки", 12, Pal.MUTED, bold = true))
        state.addView(spacer(6))
        state.addView(
            txt(
                buildString {
                    appendLine(
                        "Заряд: " + (heyBattery?.let { "$it%" + if (heyCharging) " · заряжается" else "" }
                            ?: "очки пока не сообщают")
                    )
                    appendLine("Модель: " + (heyModel ?: "не определена"))
                    appendLine("Прошивка: " + (heyFirmware ?: "нет данных"))
                    if (heyGlassWork >= 0) {
                        appendLine(
                            "Очки сообщают: " + HeyCyan.workName(heyGlassWork) +
                                (if (heyGlassError > 0) " · прошлая команда с ошибкой ${heyGlassError}" else "")
                        )
                    }
                    if (heyVideoOn) appendLine("🎥 Идёт видеозапись (подтверждено очками)")
                    if (heyVideoLimit > 0) appendLine("Предел одной записи на очках: $heyVideoLimit с")
                    if (heyAudioOn) appendLine("🎤 Идёт запись звука (подтверждено очками)")
                    if (heyFiles >= 0) appendLine("Файлов на очках: $heyFiles")
                    if (heyFilesRaw.isNotBlank()) appendLine("Ответ по файлам: $heyFilesRaw")
                    if (heyStreamCount > 0) {
                        appendLine("Поток от очков: $heyStreamCount пакетов · ${heyStreamBytes / 1024} КБ")
                    }
                    append("Последний ответ: " + (heyLastResponse.ifBlank { "пока ничего не приходило" }))
                },
                11,
                Pal.TEXT,
                mono = false
            )
        )
        if (camera.isCapturing()) {
            state.addView(spacer(6))
            state.addView(txt("📷 $captureStatus ${if (captureDetail.isBlank()) "" else "· $captureDetail"}", 11, Pal.ACCENT))
        }
        state.addView(spacer(10))
        val stateRow = row()
        stateRow.addView(actionButton("Обновить данные", primary = true) { heyRefresh() })
        if (!connected) {
            stateRow.addView(actionButton("Подключиться", primary = false) {
                val item = lastConnItem
                if (item != null) connectTo(item) else { tab = TAB_SCAN; rebuild() }
            })
        }
        state.addView(stateRow)
        c.addView(state)

        // Тревожная плашка: камера занята режимом передачи — съёмка не сработает.
        if (HeyCyan.cameraBusy(heyGlassWork)) {
            val warn = card()
            warn.addView(
                txt(
                    "Камера занята: очки в режиме «${HeyCyan.workName(heyGlassWork)}»",
                    13,
                    Pal.AMBER,
                    bold = true
                )
            )
            warn.addView(
                txt(
                    "Пока очки в этом режиме, команды съёмки формально принимаются, но кадр не снимается. " +
                        "Выйдите из режима и повторите.",
                    11,
                    Pal.MUTED
                )
            )
            warn.addView(spacer(8))
            warn.addView(actionButton("Выйти из режима передачи", primary = true) { heyExitTransfer() })
            c.addView(warn)
        }

        // Действия
        val acts = card()
        acts.addView(txt("Что сделать", 12, Pal.MUTED, bold = true))
        acts.addView(spacer(6))
        val r1 = row()
        r1.addView(heyTile("📷", "Фото", "снять кадр и получить его в приложение") { heyAction("photo") })
        r1.addView(
            heyTile(
                if (heyVideoOn) "⏹" else "🎬",
                if (heyVideoOn) "Стоп видео" else "Видео",
                if (heyVideoOn) "очки пишут — остановить" else "начать запись видео"
            ) { heyAction("video") }
        )
        acts.addView(r1)
        val r2 = row()
        r2.addView(
            heyTile(
                if (heyAudioOn) "⏹" else "🎤",
                if (heyAudioOn) "Стоп звука" else "Звук",
                if (heyAudioOn) "запись идёт — остановить" else "диктофон на очках"
            ) { heyAction("voice") }
        )
        r2.addView(heyTile("🤖", "Помощник", "включить голосового ассистента") { heyAction("assistant") })
        acts.addView(r2)
        val r3 = row()
        r3.addView(heyTile("📥", "Файлы с очков", "видео, звук, полноразмерные фото") { heyAction("files") })
        r3.addView(heyTile("🔋", "Заряд и связь", "опросить состояние") { heyAction("battery") })
        acts.addView(r3)
        acts.addView(spacer(6))
        acts.addView(
            txt(
                "Фото очки присылают сразу: по Bluetooth приходит сам снимок (миниатюра). " +
                    "Видео и звук остаются в памяти очков — их забирают по Wi-Fi очков.",
                11,
                Pal.MUTED
            )
        )
        c.addView(acts)

        if (heyActionStatus.isNotBlank()) {
            val st = card()
            st.addView(txt(heyActionStatus, 12, Pal.AMBER))
            c.addView(st)
        }

        if (heyPhotoStatus.isNotBlank()) {
            val pc = card()
            pc.addView(txt("Снимок с очков", 12, Pal.MUTED, bold = true))
            pc.addView(spacer(6))
            pc.addView(txt(heyPhotoStatus, 12, Pal.TEXT))
            pc.addView(spacer(8))
            pc.addView(actionButton("Забрать снимок ещё раз", primary = false) {
                heyStartThumb("повторный запрос")
            })
            val bmp = heyPhotoBitmap
            if (bmp != null) {
                pc.addView(spacer(8))
                val img = ImageView(this)
                img.setImageBitmap(bmp)
                img.adjustViewBounds = true
                img.scaleType = ImageView.ScaleType.FIT_CENTER
                img.layoutParams = LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT,
                    dp(240)
                )
                pc.addView(img)
            }
            c.addView(pc)
        }

        if (heyFilesOpen) c.addView(heyFilesCard())

        // Спец-инструменты спрятаны: обычному пользователю они не нужны.
        val adv = card()
        val advHead = row()
        advHead.addView(
            txt("Для специалиста", 12, Pal.MUTED, bold = true),
            LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
        )
        advHead.addView(pill(if (heyAdvanced) "скрыть" else "показать", false) {
            heyAdvanced = !heyAdvanced
            rebuild()
        })
        adv.addView(advHead)
        if (!heyAdvanced) {
            adv.addView(txt("Ручная отправка кадров, опрос протокола и HEX-журнал.", 11, Pal.MUTED))
        } else {
            adv.addView(spacer(8))
            adv.addView(
                txt(
                    "Канал A — сервис 6E40FFF0 (16 байт, последний = сумма). Канал B — DE5BF728 " +
                        "(BC, тип, длина, CRC16). Каждый кадр виден в журнале.",
                    11,
                    Pal.MUTED
                )
            )
            adv.addView(spacer(8))
            adv.addView(actionButton("Опросить протокол", primary = false) { runHeyProbe() })
            adv.addView(spacer(8))
            val chanRow = row()
            chanRow.addView(pill("A · команды", heyChannel == HeyCyan.CH_CTRL) {
                heyChannel = HeyCyan.CH_CTRL
                rebuild()
            })
            chanRow.addView(pill("B · BC-кадры", heyChannel == HeyCyan.CH_SERIAL) {
                heyChannel = HeyCyan.CH_SERIAL
                rebuild()
            })
            adv.addView(chanRow)
            adv.addView(spacer(8))
            val hexInput = input("HEX, например 02 05")
            adv.addView(hexInput)
            val typeInput = input("Тип для BC-кадра (HEX)", heyTypeText)
            adv.addView(typeInput)
            val rawRow = row()
            rawRow.addView(actionButton("Отправить как есть", primary = false) {
                val bytes = HeyCyan.parseHex(hexInput.text.toString())
                if (bytes == null || bytes.isEmpty()) {
                    toast("Нужны целые байты в HEX")
                } else {
                    heySendRaw(heyChannel, bytes, "свои байты")
                }
            })
            rawRow.addView(actionButton("Обернуть в BC", primary = true) {
                heyTypeText = typeInput.text.toString().ifBlank { "41" }
                val bytes = HeyCyan.parseHex(hexInput.text.toString()) ?: ByteArray(0)
                val type = HeyCyan.parseHex(heyTypeText)?.firstOrNull()?.toInt()?.and(0xFF) ?: 0x41
                heySend(HeyCyan.CH_SERIAL, type, bytes, "BC-кадр 0x" + String.format("%02X", type))
            })
            adv.addView(rawRow)
            adv.addView(spacer(8))
            adv.addView(actionButton("Копировать журнал", primary = false) { copyHeyLog() })
            adv.addView(spacer(6))
            val tail = logs.takeLast(10).joinToString("\n").ifBlank { "Пока пусто" }
            adv.addView(txt(tail, 10, Pal.MUTED, mono = true))
        }
        c.addView(adv)
        return c
    }

    /** Карточка «забрать файлы»: честно объясняет, что медиа идут по Wi-Fi очков. */
    private fun heyFilesCard(): View {
        val box = card()
        box.addView(txt("Фото, видео и звук с очков", 12, Pal.MUTED, bold = true))
        box.addView(spacer(6))
        box.addView(
            txt(
                "Полноразмерные файлы лежат в памяти очков, а не в Bluetooth: очки поднимают " +
                    "свою Wi-Fi-сеть, и приложение скачивает их по ней. На время выгрузки камера занята — " +
                    "после неё приложение само выйдет из режима передачи.",
                11,
                Pal.MUTED
            )
        )
        if (heyMediaStatus.isNotBlank()) {
            box.addView(spacer(8))
            box.addView(txt(heyMediaStatus, 12, Pal.TEXT))
        }
        if (heyWifiSsid.isNotBlank()) {
            box.addView(spacer(4))
            box.addView(txt("Сеть очков: «$heyWifiSsid»", 11, Pal.MUTED))
        }
        if (heyP2pIp != null) {
            box.addView(txt("Адрес очков: ${heyP2pIp}", 11, Pal.MUTED, mono = true))
        }
        if (heyMediaNames.isNotEmpty()) {
            box.addView(spacer(6))
            box.addView(
                txt(
                    heyMediaNames.take(12).joinToString("\n") { "• $it" } +
                        if (heyMediaNames.size > 12) "\n… и ещё ${heyMediaNames.size - 12}" else "",
                    11,
                    Pal.TEXT,
                    mono = true
                )
            )
        }
        box.addView(spacer(10))
        val b1 = row()
        b1.addView(actionButton("Включить Wi-Fi и скачать", primary = true) { heyFilesGrab() })
        if (heyTransferOn) b1.addView(actionButton("Выйти из передачи", primary = false) { heyExitTransfer() })
        box.addView(b1)
        box.addView(spacer(6))
        val b2 = row()
        b2.addView(actionButton("Повторить выгрузку", primary = false) { heyStartMediaSync() })
        b2.addView(actionButton("Остановить", primary = false) { heyMediaCancel() })
        box.addView(b2)
        if (heyWifi.isNotEmpty()) {
            box.addView(spacer(8))
            box.addView(txt("Сети рядом:", 11, Pal.MUTED))
            box.addView(spacer(4))
            box.addView(
                txt(
                    heyWifi.take(10).joinToString("\n") { (ssid, level) -> "$ssid   $level dBm" },
                    11,
                    Pal.TEXT,
                    mono = true
                )
            )
        }
        box.addView(spacer(8))
        box.addView(actionButton("Найти сеть очков", primary = false) { heyScanWifi() })
        box.addView(spacer(6))
        box.addView(actionButton("Открыть Wi-Fi настройки", primary = false) {
            wifi.openWifiSettings()
        })
        return box
    }

    private fun heyFilesGrab() {
        heyFilesOpen = true
        heySubscribeProtocol()
        // SDK: показать, сколько файлов лежит в памяти, и включить Wi-Fi на очках.
        heySendSequence(
            listOf(
                HeyTx(HeyCyan.CH_SERIAL, 0x41, byteArrayOf(0x02, 0x04)),
                HeyTx(HeyCyan.CH_SERIAL, 0x41, HeyCyan.control(HeyCyan.Work.TRANSFER))
            ),
            "Режим передачи"
        )
        heyTransferOn = true
        heyMediaStatus = "Очки включают свою Wi-Fi-сеть…"
        heyActionStatus = "Идёт выгрузка по Wi-Fi очков. Камера в это время занята — " +
            "после выгрузки приложение само выйдет из режима передачи."
    }

    // ---------- Выгрузка файлов по Wi-Fi очков ----------

    /**
     * Полный путь к файлам: очки включают свою точку доступа, отдают имя сети
     * и пароль в ответе на команду передачи, приложение подключается к этой сети
     * и скачивает /files/media.config и сами файлы по HTTP.
     */
    private fun heyStartMediaSync() {
        if (connState != ConnState.CONNECTED) return
        if (heyWifiSsid.isBlank()) {
            heyMediaStatus = NO_CREDS_TEXT
            if (tab == TAB_HEY) rebuild()
            return
        }
        // Android 13+ требует разрешение «устройства поблизости» для Wi-Fi.
        if (Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(Manifest.permission.NEARBY_WIFI_DEVICES) != PackageManager.PERMISSION_GRANTED
        ) {
            pendingAfterPermission = { heyStartMediaSync() }
            requestPermissions(arrayOf(Manifest.permission.NEARBY_WIFI_DEVICES), REQ_WIFI)
            return
        }
        heyMediaSaved = 0
        heyMediaNames = emptyList()
        heyMediaStatus = "Подключаюсь к Wi-Fi очков «$heyWifiSsid»…"
        if (tab == TAB_HEY) rebuild()
        heyMedia = GlassesMedia(this, wifi).also { engine ->
            engine.sync(heyWifiSsid, heyWifiPass, heyP2pIp, object : GlassesMedia.Listener {
                override fun onStatus(text: String) {
                    ui.post {
                        heyMediaStatus = text
                        if (tab == TAB_HEY) rebuildThrottled()
                    }
                }

                override fun onLog(line: String) {
                    ui.post { addLog(line) }
                }

                override fun onFiles(total: Int, names: List<String>) {
                    ui.post {
                        heyMediaNames = names
                        heyFiles = total
                        heyFilesRaw = names.take(20).joinToString(", ")
                        heyMediaStatus = "На очках файлов: $total. Скачиваю…"
                        if (tab == TAB_HEY) rebuild()
                    }
                }

                override fun onProgress(index: Int, total: Int, name: String) {
                    ui.post {
                        heyMediaStatus = "Скачиваю $index из $total: $name"
                        if (tab == TAB_HEY) rebuildThrottled()
                    }
                }

                override fun onSaved(file: File, isImage: Boolean) {
                    ui.post {
                        heyMediaSaved += 1
                        if (isImage) {
                            lastPhoto = file
                            lastPhotoBitmap = thumb(file, 480)
                        }
                    }
                }

                override fun onFinished(ok: Boolean, message: String) {
                    ui.post {
                        heyMediaStatus = message
                        addLog("Файлы с очков: $message")
                        // Очки в режиме передачи держат камеру занятой — отпускаем её.
                        if (ok && heyTransferOn) {
                            ui.postDelayed({ heyExitTransfer() }, 1200)
                        }
                        if (tab == TAB_HEY) rebuild()
                    }
                }
            })
        }
    }

    private fun heyMediaCancel() {
        heyMedia?.cancel()
        heyMedia = null
        heyMediaStatus = "Выгрузка остановлена."
        if (tab == TAB_HEY) rebuild()
    }

    private fun heyScanWifi() {
        heyFilesOpen = true
        heyWifi = wifi.scanNetworks()
        heyActionStatus = if (heyWifi.isEmpty()) {
            "Сети не найдены. Проверьте, что очки включены и режим Wi-Fi активирован."
        } else {
            "Найдено сетей: ${heyWifi.size}. Обычно сеть очков называется W630, AM01, HeyCyan или GLASSES."
        }
        rebuild()
    }

    private fun isHeyCyanDevice(): Boolean = heyAvailable()

    private fun heyAction(id: String) {
        if (connState != ConnState.CONNECTED) {
            toast("Сначала подключитесь к очкам")
            return
        }
        when (id) {
            "photo" -> heyTakePhoto()
            "video" -> heyToggleVideo()
            "voice" -> heyToggleAudio()
            "assistant" -> heyToggleAssistant()
            "files" -> {
                heyFilesOpen = !heyFilesOpen
                heyActionStatus = if (heyFilesOpen)
                    "Файлы очки отдают по своей Wi-Fi-сети — инструкция ниже."
                else ""
                rebuild()
            }
            "battery" -> heyRefresh()
        }
    }

    /**
     * Снять фото. Команда идёт в канал B кадром BC 41 [02 01 01].
     * Доказательство съёмки — ответ очков с кодом ошибки 0, а сам кадр забираем
     * миниатюрой (BC FD) — она приходит по Bluetooth целиком.
     */
    /**
     * Снять фото.
     *
     * Главная причина прошлых «фиктивных» команд: очки могут стоять в режиме
     * передачи файлов (workType 4). В нём камера занята, и любая команда
     * съёмки формально принимается (errorCode 0), но физически не выполняется.
     * Поэтому сначала выходим из этого режима штатной командой TransferStop (0x09),
     * синхронизируем время (очки именуют файлы по своим часам) и только потом снимаем.
     * А проверяем результат не по коду ответа, а по счётчику файлов на очках.
     */
    private fun heyTakePhoto() {
        heySubscribeProtocol()
        heyPhotoStatus = "Готовлю съёмку…"
        heyActionStatus = ""
        rebuild()

        val shutter = Runnable { heyFireShutter(aiQuality = false) }

        if (HeyCyan.cameraBusy(heyGlassWork)) {
            heyActionStatus = "Очки в режиме «${HeyCyan.workName(heyGlassWork)}» — камера занята. " +
                "Выхожу из него и снимаю."
            heySend(HeyCyan.CH_SERIAL, 0x41, HeyCyan.control(HeyCyan.Work.TRANSFER_STOP), "Выход из режима передачи")
            ui.postDelayed(shutter, 1800)
        } else {
            shutter.run()
        }
    }

    /**
     * Собственно затвор. Сначала обычная команда фото (0x01). Если очки её приняли,
     * но кадра нет — повторяем с настройкой качества, как в официальном приложении
     * (0x06): именно этот путь включает ИИ-снимок и гарантированно отдаёт миниатюру.
     */
    private fun heyFireShutter(aiQuality: Boolean) {
        if (connState != ConnState.CONNECTED) {
            toast("Сначала подключитесь к очкам")
            return
        }
        if (aiQuality) {
            heySend(HeyCyan.CH_SERIAL, 0x41, HeyCyan.photoQuality(2), "Фото: качество")
            ui.postDelayed({
                heyExpectPhoto = true
                heyPhotoBaseline = heyPhotos
                heySend(HeyCyan.CH_SERIAL, 0x41, HeyCyan.control(HeyCyan.Work.PHOTO_AI), "Фото: кадр (ИИ)")
                heyActionStatus = "Фото: команда отправлена, ждём ответ очков…"
                ui.postDelayed({ heyStartThumb("фото (ИИ)") }, 2500)
            }, 500)
        } else {
            heyExpectPhoto = true
            heyPhotoBaseline = heyPhotos
            heySend(HeyCyan.CH_SERIAL, 0x41, HeyCyan.control(HeyCyan.Work.PHOTO), "Фото: снять")
            heyActionStatus = "Фото: команда отправлена, ждём ответ очков…"
            ui.postDelayed({ heyRequestCounts() }, 3500)
            ui.postDelayed({ if (heyThumbParts.isEmpty()) heyStartThumb("фото") }, 3000)
        }
    }

    /** Выйти из режима передачи файлов: именно он блокирует камеру. */
    private fun heyExitTransfer() {
        heySubscribeProtocol()
        heyMedia?.cancel()
        heyMedia = null
        heyTransferOn = false
        heyStopPulse()
        heyActionStatus = "Отправляю «выйти из режима передачи»…"
        rebuild()
        heySend(HeyCyan.CH_SERIAL, 0x41, HeyCyan.control(HeyCyan.Work.TRANSFER_STOP), "Выход из режима передачи")
        ui.postDelayed({
            if (HeyCyan.cameraBusy(heyGlassWork)) {
                // Штатный выход не сработал — тогда сброс Wi-Fi, как делает сам SDK.
                addLog("Режим передачи не снялся — отправляю сброс Wi-Fi (0x0F)")
                heySend(HeyCyan.CH_SERIAL, 0x41, HeyCyan.control(HeyCyan.Work.NO_POWER_P2P), "Сброс Wi-Fi")
            }
        }, 2500)
    }

    /** Спросить у очков, сколько файлов лежит в памяти. */
    private fun heyRequestCounts() {
        heySend(HeyCyan.CH_SERIAL, 0x41, byteArrayOf(0x02, 0x04), "Счётчик файлов")
    }

    /**
     * Видео.
     *
     * Две вещи, без которых очки сами прекращают запись через пару секунд:
     *  1) у очков есть предельная длительность записи — её задаём явно (60 с);
     *  2) пока идёт запись, приложение должно регулярно посылать «пульс» (0x45),
     *     иначе прошивка решает, что хозяин отвязался, и закрывает файл.
     */
    private fun heyToggleVideo() {
        heySubscribeProtocol()
        val start = !heyVideoOn
        rebuild()
        if (start) {
            if (HeyCyan.cameraBusy(heyGlassWork)) {
                heyActionStatus = "Очки в режиме «${HeyCyan.workName(heyGlassWork)}» — сначала выхожу из него."
                heySend(HeyCyan.CH_SERIAL, 0x41, HeyCyan.control(HeyCyan.Work.TRANSFER_STOP), "Выход из режима передачи")
                ui.postDelayed({ heyStartVideo() }, 1800)
                return
            }
            heyStartVideo()
        } else {
            heyActionStatus = "Видео: отправляю «остановить запись»…"
            heyWantVideo = false
            heyStartPulse()
            heySend(HeyCyan.CH_SERIAL, 0x41, HeyCyan.control(HeyCyan.Work.VIDEO_STOP), "Видео: стоп")
            ui.postDelayed({
                if (heyVideoOn) {
                    // Прошивка не поняла отдельный стоп — шлём тот же «старт» (переключатель).
                    heySend(HeyCyan.CH_SERIAL, 0x41, HeyCyan.control(HeyCyan.Work.VIDEO_START), "Видео: стоп (переключатель)")
                }
            }, 2500)
        }
    }

    private fun heyStartVideo() {
        // 60 секунд — разумный предел на одну запись; очки принимают это значение.
        heySend(HeyCyan.CH_SERIAL, 0x41, HeyCyan.setVideoDuration(60), "Видео: предел 60 с")
        heyVideoLimit = 60
        ui.postDelayed({
            heyWantVideo = true
            heyWantAudio = false
            heySend(HeyCyan.CH_SERIAL, 0x41, HeyCyan.control(HeyCyan.Work.VIDEO_START), "Видео: старт")
            heyActionStatus = "Видео: запись начата. Держу связь с очками, чтобы они не остановили её сами."
            heyStartPulse()
            ui.postDelayed({ heySend(HeyCyan.CH_SERIAL, 0x41, HeyCyan.query(2), "Видео: настройки") }, 1500)
        }, 500)
    }

    private fun heyToggleAudio() {
        heySubscribeProtocol()
        val start = !heyAudioOn
        rebuild()
        if (start) {
            heySend(HeyCyan.CH_SERIAL, 0x41, HeyCyan.setAudioDuration(300), "Звук: предел 5 мин")
            ui.postDelayed({
                heyWantAudio = true
                heyWantVideo = false
                heySend(HeyCyan.CH_SERIAL, 0x41, HeyCyan.control(HeyCyan.Work.AUDIO_START), "Звук: старт")
                heyActionStatus = "Запись звука начата."
                heyStartPulse()
            }, 400)
        } else {
            heyActionStatus = "Запись звука: отправляю «остановить»…"
            heyWantAudio = false
            heyStartPulse()
            heySend(HeyCyan.CH_SERIAL, 0x41, HeyCyan.control(HeyCyan.Work.AUDIO_STOP), "Звук: стоп")
            ui.postDelayed({
                if (heyAudioOn) {
                    heySend(HeyCyan.CH_SERIAL, 0x41, HeyCyan.control(HeyCyan.Work.AUDIO_START), "Звук: стоп (переключатель)")
                }
            }, 2500)
        }
    }

    /**
     * «Пульс» для очков: пока идёт запись или открыт режим передачи, раз в 1.5 с
     * отправляем BC 45 [режим, 01]. Официальное приложение делает так же.
     */
    private fun heyStartPulse() {
        if (heyPulse != null) return
        val tick = object : Runnable {
            override fun run() {
                if (connState != ConnState.CONNECTED) {
                    heyPulse = null
                    return
                }
                when {
                    heyWantVideo -> heySendSilent(0x45, byteArrayOf(HeyCyan.Work.VIDEO_START.toByte(), 0x01))
                    heyWantAudio -> heySendSilent(0x45, byteArrayOf(HeyCyan.Work.AUDIO_START.toByte(), 0x01))
                    heyTransferOn -> heySendSilent(0x45, byteArrayOf(HeyCyan.Work.TRANSFER.toByte(), 0x01))
                }
                ui.postDelayed(this, 1500)
            }
        }
        heyPulse = tick
        ui.postDelayed(tick, 1500)
    }

    private fun heyStopPulse() {
        heyPulse?.let { ui.removeCallbacks(it) }
        heyPulse = null
    }

    /** Отправка без записи в журнал — для служебного «пульса». */
    private fun heySendSilent(cmd: Int, payload: ByteArray) {
        if (connState != ConnState.CONNECTED || ble.busySubscribing) return
        val frame = HeyCyan.frameFor(HeyCyan.CH_SERIAL, cmd, payload)
        ble.write(HeyCyan.SERIAL_SERVICE, HeyCyan.SERIAL_WRITE, frame, withResponse = false)
    }

    /**
     * Помощник. Очки умеют только открыть микрофон и включить распознавание речи:
     * сам разговор (распознавание, ответ, озвучка) ведёт приложение HeyCyan в облаке.
     * Поэтому мы честно включаем микрофон очков и подсказываем, что дальше нужен
     * их собственный ассистент.
     */
    private fun heyToggleAssistant() {
        heySubscribeProtocol()
        heyActionStatus = "Помощник: включаю микрофон очков…"
        rebuild()
        heySend(HeyCyan.CH_SERIAL, 0x44, HeyCyan.aiVoiceWakePayload(true), "Помощник: микрофон")
        ui.postDelayed({
            heySend(HeyCyan.CH_SERIAL, 0x41, HeyCyan.control(HeyCyan.Work.ASSISTANT), "Помощник: режим")
            heyActionStatus = "Микрофон очков включён. Ответы и озвучку ведёт приложение HeyCyan: " +
                "у нас нет их облака, поэтому очки только слушают."
        }, 500)
        ui.postDelayed({
            if (connState == ConnState.CONNECTED) {
                heySend(HeyCyan.CH_SERIAL, 0x41, HeyCyan.control(HeyCyan.Work.STOP_AI), "Помощник: стоп")
            }
        }, 15000)
    }

    data class HeyTx(val channel: String, val cmd: Int, val payload: ByteArray)

    /** Отправляет последовательность кадров с паузами: GATT не любит очередь из записей. */
    private fun heySendSequence(frames: List<HeyTx>, title: String) {
        heyActionStatus = "$title: отправляю…"
        heySendTitle = title
        var index = 0
        val step = object : Runnable {
            override fun run() {
                if (index >= frames.size) {
                    heyActionStatus = "$title: команда отправлена. " +
                        if (heyLastResponse.isBlank()) "Ответа от очков пока нет."
                        else "Ответ: $heyLastResponse"
                    rebuild()
                    return
                }
                val f = frames[index]
                index += 1
                heySend(f.channel, f.cmd, f.payload, title)
                ui.postDelayed(this, 500)
            }
        }
        ui.postDelayed(step, 60)
    }

    /** Опросить заряд и сведения об очках. */
    private fun heyRefresh() {
        if (connState != ConnState.CONNECTED) {
            toast("Сначала подключитесь к очкам")
            return
        }
        heySubscribeProtocol()
        heyActionStatus = "Обновляю данные очков…"
        heySendSequence(
            listOf(
                HeyTx(HeyCyan.CH_SERIAL, 0x42, byteArrayOf(0x00, 0x00)),
                HeyTx(HeyCyan.CH_CTRL, 0x03, ByteArray(0)),
                HeyTx(HeyCyan.CH_CTRL, 0x3C, ByteArray(0)),
                HeyTx(HeyCyan.CH_CTRL, 0xA1, byteArrayOf(0x01)),
                HeyTx(HeyCyan.CH_SERIAL, 0x41, byteArrayOf(0x02, 0x04)),
                HeyTx(HeyCyan.CH_SERIAL, 0x41, HeyCyan.query(2)),
                HeyTx(HeyCyan.CH_SERIAL, 0x43, byteArrayOf(0x00, 0x00))
            ),
            "Заряд и сведения"
        )
    }

    private fun heySubscribeProtocol() {
        for ((service, char) in listOf(
            HeyCyan.CTRL_SERVICE to HeyCyan.CTRL_NOTIFY,
            HeyCyan.SERIAL_SERVICE to HeyCyan.SERIAL_NOTIFY
        )) {
            if (subscribed.add("$service|$char")) ble.subscribe(service, char, true)
        }
        for (service in gattServices) {
            for (char in service.chars) {
                if (char.notifiable && subscribed.add("${service.uuid}|${char.uuid}")) {
                    ble.subscribe(service.uuid, char.uuid, true)
                }
            }
        }
    }

    private fun heySend(channel: String, type: Int, payload: ByteArray, title: String, quiet: Boolean = false) {
        if (!quiet) heySendTitle = title
        val frame = HeyCyan.frameFor(channel, type, payload)
        heySendRaw(channel, frame, title, quiet = quiet)
    }

    private fun heySendRaw(channel: String, frame: ByteArray, title: String, attempt: Int = 0, quiet: Boolean = false) {
        if (connState != ConnState.CONNECTED) {
            if (!quiet) toast("Сначала подключитесь к устройству")
            return
        }
        val service = if (channel == HeyCyan.CH_CTRL) HeyCyan.CTRL_SERVICE else HeyCyan.SERIAL_SERVICE
        val char = if (channel == HeyCyan.CH_CTRL) HeyCyan.CTRL_WRITE else HeyCyan.SERIAL_WRITE
        if (ble.busySubscribing) {
            // Ещё пишется дескриптор подписки: подождём, иначе GATT отклонит запись.
            ui.postDelayed({ heySendRaw(channel, frame, title, attempt, quiet) }, 250)
            return
        }
        // Канал A у SDK — обычная запись с ответом, канал B — без ответа.
        val ok = ble.write(service, char, frame, withResponse = if (channel == HeyCyan.CH_CTRL) null else false)
        heyLastTx = frame
        heyLastTxAt = System.currentTimeMillis()
        if (ok) {
            if (!quiet) addLog("→ Очки · $title · ${HeyCyan.hex(frame)}")
        } else if (attempt < 2) {
            // GATT занят предыдущей операцией — повторяем, это обычное дело на Android.
            ui.postDelayed({ heySendRaw(channel, frame, title, attempt + 1, quiet) }, 400)
        } else {
            addLog("Очки · $title: запись не принята")
            heyActionStatus = "$title: очки не приняли команду"
        }
        if (tab == TAB_HEY && !quiet) rebuildThrottled()
    }

    /** Разбор всего, что прилетает в уведомления, в человеческий текст. */
    /**
     * Разбор уведомлений. Возвращает true, если кадр относится к протоколу очков:
     * тогда вызывающий не пишет его в журнал простым текстом (иначе журнал тонет).
     */
    private fun heyObserve(value: ByteArray): Boolean {
        if (HeyCyan.isBigFrame(value)) {
            // Канал B режет длинные кадры по MTU — сначала склеиваем, потом разбираем.
            for (frame in heyFramer.push(value)) heyHandleFrame(frame)
            return true
        }
        if (value.size == HeyCyan.FRAME_LEN) {
            heyHandleFrame(value)
            return true
        }
        return false
    }

    private fun heyHandleFrame(value: ByteArray) {
        HeyCyan.batteryInfo(value)?.let {
            heyBattery = it.level
            heyCharging = it.charging
        }
        if (HeyCyan.isStreamFrame(value)) {
            // Служебный поток очков идёт десятками пакетов в секунду: считаем, но не засоряем журнал.
            heyStreamCount += 1
            heyStreamBytes += value.size
            if (heyStreamCount == 1) {
                addLog("Очки начали поток данных: ${HeyCyan.hex(value.take(16).toByteArray())}")
            } else if (heyStreamCount - heyStreamLogged >= 200) {
                heyStreamLogged = heyStreamCount
                addLog("Поток данных: $heyStreamCount пакетов, ${heyStreamBytes / 1024} КБ")
            }
            return
        }

        // События очков (тип 0x73). Самое важное — 09 FF: Wi-Fi у очков не поднялся,
        // SDK в этом случае шлёт «сброс Wi-Fi» (0x0F), иначе очки залипают.
        HeyCyan.deviceEvent(value)?.let { ev ->
            if (HeyCyan.wifiFailed(value)) {
                addLog("Очки: Wi-Fi не поднялся (73 09 FF) — отправляю сброс Wi-Fi")
                heySend(HeyCyan.CH_SERIAL, 0x41, HeyCyan.control(HeyCyan.Work.NO_POWER_P2P), "Сброс Wi-Fi")
            } else if (ev.type != 0x0B) {
                val now = System.currentTimeMillis()
                if (now - heyLastEventAt > 1500) {
                    heyLastEventAt = now
                    addLog("Событие очков: ${HeyCyan.eventName(ev.type)} (${ev.value})")
                }
            }
            if (tab == TAB_HEY) rebuildThrottled()
            return
        }

        // Очки прислали имя и пароль своей Wi-Fi-сети — это ключ к выгрузке файлов.
        HeyCyan.transferCredentials(value)?.let { creds ->
            if (creds.ssid != heyWifiSsid) {
                heyWifiSsid = creds.ssid
                heyWifiPass = creds.password
                addLog("Wi-Fi очков: сеть «${creds.ssid}»" + if (creds.password.isBlank()) " без пароля" else " с паролем")
                if (heyTransferOn) {
                    ui.postDelayed({ heyStartMediaSync() }, 400)
                }
            }
        }

        // Ответ очков на команду управления: что просили, ошибка, что сейчас.
        HeyCyan.glassState(value)?.let { st ->
            heyOnGlassState(st)
            return
        }

        // Миниатюра снимка: в каждом кадре — кусок JPEG с номером.
        HeyCyan.thumbChunk(value)?.let { chunk ->
            heyOnThumbChunk(chunk)
            return
        }

        // Счётчики файлов. Это независимая проверка съёмки: очки сами говорят,
        // стало ли файлов больше.
        HeyCyan.mediaCounts(value)?.let { counts ->
            val baseline = if (heyPhotoBaseline >= 0) heyPhotoBaseline else heyPhotos
            heyPhotos = counts.photos
            heyVideos = counts.videos
            heyRecords = counts.records
            heyFiles = counts.photos + counts.videos + counts.records
            heyFilesRaw = "${counts.photos} фото · ${counts.videos} видео · ${counts.records} записей"
            if (heyExpectPhoto && baseline >= 0) {
                heyExpectPhoto = false
                if (counts.photos > baseline) {
                    addLog("Счётчик фото вырос: $baseline → ${counts.photos}")
                    if (heyPhotoStatus.isBlank()) {
                        heyPhotoStatus = "Очки подтвердили новый кадр (файлов было $baseline, стало ${counts.photos})."
                    }
                } else {
                    heyPhotoStatus = "Счётчик фото не изменился (${counts.photos}) — кадр, похоже, не сохранился."
                }
            }
            return
        }

        // Настройки записи: длительность видео/звука и адрес очков в их Wi-Fi.
        HeyCyan.videoDuration(value)?.let { seconds ->
            heyVideoLimit = seconds
            addLog("Очки: предел записи видео — $seconds с")
            return
        }
        HeyCyan.deviceIp(value)?.let { ip ->
            heyP2pIp = ip
            addLog("Адрес очков в их Wi-Fi: $ip")
            return
        }

        val echo = heyLastTx?.let { it.contentEquals(value) } == true &&
            System.currentTimeMillis() - heyLastTxAt < 8000
        heyLastResponse = if (echo) {
            "эхо нашей записи (не ответ очков)"
        } else {
            HeyCyan.friendly(value) ?: HeyCyan.describe(value) ?: HeyCyan.hex(value.take(24).toByteArray())
        }
    }

    /** Очки ответили на команду: только этот ответ и считается подтверждением. */
    private fun heyOnGlassState(st: HeyCyan.GlassState) {
        val previous = heyGlassWork
        heyGlassWork = st.running
        heyGlassError = st.error
        // Текущее состояние берём из ответа очков, а не из наших надежд.
        heyVideoOn = st.running == HeyCyan.Work.VIDEO_START
        heyAudioOn = st.running == HeyCyan.Work.AUDIO_START
        if (previous != st.running) {
            addLog("Режим очков: ${HeyCyan.workName(st.running)}")
        }
        if (st.error != 0) {
            heyActionStatus = "Очки отказали: «${HeyCyan.workName(st.work)}» (код ${st.error})" +
                " · сейчас: ${HeyCyan.workName(st.running)}"
            return
        }
        heyActionStatus = "Очки подтвердили: ${HeyCyan.workName(st.work)}" +
            if (st.running != st.work) " · сейчас: ${HeyCyan.workName(st.running)}" else ""
        when (st.work) {
            HeyCyan.Work.PHOTO, HeyCyan.Work.PHOTO_AI -> {
                if (HeyCyan.cameraBusy(st.running)) {
                    heyPhotoStatus = "Очки приняли команду, но остались в режиме «" +
                        HeyCyan.workName(st.running) + "» — кадр не снят. " +
                        "Нажмите «Выйти из режима передачи» и повторите."
                } else {
                    heyPhotoStatus = "Очки приняли команду съёмки. Забираю снимок…"
                    ui.postDelayed({ if (heyThumbParts.isEmpty()) heyStartThumb("фото") }, 1200)
                }
            }
            HeyCyan.Work.TRANSFER -> {
                heyTransferOn = true
                heyStartPulse()
                if (heyWifiSsid.isNotBlank()) {
                    heyStartMediaSync()
                } else {
                    heyActionStatus = "Очки включили свою Wi-Fi-сеть. Жду от них имя сети…"
                    ui.postDelayed({
                        heySend(HeyCyan.CH_SERIAL, 0x41, HeyCyan.query(3), "Адрес очков")
                        ui.postDelayed({ if (heyWifiSsid.isBlank()) heyMediaStatus = NO_CREDS_TEXT }, 4000)
                    }, 1200)
                }
            }
            HeyCyan.Work.TRANSFER_STOP -> {
                heyTransferOn = false
                heyStopPulse()
                heyPhotoStatus = heyPhotoStatus.ifBlank { "Очки вышли из режима передачи — камера свободна." }
            }
            HeyCyan.Work.VIDEO_START -> heyStartPulse()
            HeyCyan.Work.VIDEO_STOP -> {
                heyWantVideo = false
                heyStartPulse()
            }
            HeyCyan.Work.AUDIO_STOP -> {
                heyWantAudio = false
                heyStartPulse()
            }
            HeyCyan.Work.AUDIO_START -> {
                heyWantAudio = true
                heyWantVideo = false
                heyStartPulse()
            }
            else -> {}
        }
    }

    // ---------- Миниатюра снимка ----------

    /**
     * Просим миниатюру последнего снимка. Очки присылают её частями, причём
     * пачкой и не по порядку — поэтому запрашиваем один раз, складываем части
     * по номерам и потом добираем только недостающие.
     */
    private fun heyStartThumb(reason: String) {
        if (connState != ConnState.CONNECTED) return
        if (heyThumbParts.isNotEmpty() || heyThumbTotal > 0) return
        heyThumbParts.clear()
        heyThumbTotal = -1
        heyThumbStartedAt = System.currentTimeMillis()
        heyThumbRounds = 0
        addLog("Прошу миниатюру снимка ($reason)")
        heySend(HeyCyan.CH_SERIAL, 0xFD, byteArrayOf(0x01, 0x00, 0x00), "Миниатюра")
        ui.postDelayed({ heyThumbWatchdog(false) }, 2000)
    }

    private fun heyOnThumbChunk(chunk: HeyCyan.ThumbChunk) {
        if (chunk.total <= 0) {
            if (heyThumbParts.isEmpty()) {
                heyPhotoStatus = "Очки ответили, что миниатюр нет — кадр не сохранился."
                addLog("Миниатюра: очки ответили «нет файлов»")
            }
            return
        }
        heyThumbTotal = chunk.total
        if (chunk.data.isNotEmpty() && !heyThumbParts.containsKey(chunk.index)) {
            heyThumbParts[chunk.index] = chunk.data
        }
        val got = heyThumbParts.size
        if (got % 5 == 0 || got == chunk.total) {
            heyPhotoStatus = "Получаю снимок: $got из ${chunk.total} частей"
            addLog("Миниатюра: $got / ${chunk.total} частей")
        }
        if (got >= chunk.total) heyFinishThumb() else if (tab == TAB_HEY) rebuildThrottled()
    }

    /**
     * Добор: если очки прислали пачку и замолчали, просим недостающие части
     * по одной. Три круга, потом честно сообщаем, чего не хватило.
     */
    private fun heyThumbWatchdog(force: Boolean) {
        val total = heyThumbTotal
        val elapsed = System.currentTimeMillis() - heyThumbStartedAt
        if (total > 0 && heyThumbParts.size >= total) {
            heyFinishThumb()
            return
        }
        if (total > 0) {
            val missing = (0 until total).filter { !heyThumbParts.containsKey(it) }
            if (missing.isNotEmpty() && (force || elapsed > 1200)) {
                if (heyThumbRounds >= 3) {
                    heyPhotoStatus = "Очки прислали ${heyThumbParts.size} из $total частей снимка и перестали отвечать. " +
                        "Попробуйте «Фото» ещё раз."
                    addLog("Миниатюра: не хватило частей ${missing.take(8)}")
                    heyThumbTotal = -1
                    return
                }
                heyThumbRounds += 1
                addLog("Миниатюра: прошу недостающие части (${missing.size})")
                var delay = 0L
                for (index in missing.take(12)) {
                    ui.postDelayed({
                        heySend(HeyCyan.CH_SERIAL, 0xFD,
                            byteArrayOf(0x01, (index and 0xFF).toByte(), ((index shr 8) and 0xFF).toByte()),
                            "Миниатюра ${index + 1}", quiet = true)
                    }, delay)
                    delay += 220
                }
                ui.postDelayed({ heyThumbWatchdog(true) }, delay + 1500)
                return
            }
        }
        if (elapsed > 20000) {
            heyPhotoStatus = "Очки не прислали миниатюру за 20 секунд. " +
                "Кадр при этом мог сохраниться в памяти очков — проверьте их приложением HeyCyan."
            addLog("Миниатюра: таймаут")
            heyThumbTotal = -1
            return
        }
        ui.postDelayed({ heyThumbWatchdog(false) }, 1200)
    }

    private fun heyFinishThumb() {
        val total = heyThumbTotal
        if (total <= 0) return
        heyThumbTotal = -1
        val buffer = java.io.ByteArrayOutputStream()
        var missing = 0
        for (index in 0 until total) {
            val part = heyThumbParts[index]
            if (part == null) missing += 1 else buffer.write(part)
        }
        if (missing > 0) {
            heyPhotoStatus = "Снимок собран не полностью: нет $missing из $total частей."
            heyThumbTotal = -1
            return
        }
        val bytes = buffer.toByteArray()
        heyThumbParts.clear()
        if (bytes.size < 4 || (bytes[0].toInt() and 0xFF) != 0xFF || (bytes[1].toInt() and 0xFF) != 0xD8) {
            heyPhotoStatus = "Очки прислали ${bytes.size} байт, но это не JPEG. " +
                "Начало: ${HeyCyan.hex(bytes.take(12).toByteArray())}"
            addLog("Миниатюра: не JPEG (${HeyCyan.hex(bytes.take(12).toByteArray())})")
            return
        }
        val file = store.save(bytes, "heycyan")
        heyPhotoBitmap = BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
        if (file != null) {
            lastPhoto = file
            lastPhotoBitmap = thumb(file, 480)
            heyPhotoStatus = "Снимок с очков получен: ${bytes.size / 1024} КБ · сохранён во вкладке «Фото»"
        } else {
            heyPhotoStatus = "Снимок получен: ${bytes.size / 1024} КБ, но сохранить файл не удалось"
        }
        addLog("Снимок с очков получен по Bluetooth: ${bytes.size} байт, частей $total")
        if (tab == TAB_HEY) rebuild()
    }

    private fun runHeyProbe() {
        if (connState != ConnState.CONNECTED) {
            toast("Сначала подключитесь к устройству")
            return
        }
        heySubscribeProtocol()
        val list = HeyCyan.probes()
        heyActionStatus = "Опрос: 0/${list.size}"
        rebuild()
        var index = 0
        val step = object : Runnable {
            override fun run() {
                if (index >= list.size) {
                    heyActionStatus = "Опрос отправлен: ${list.size} кадров. Подробности — в журнале."
                    addLog("Опрос очков завершён: кадров ${list.size}")
                    rebuild()
                    return
                }
                val probe = list[index]
                index += 1
                heySend(probe.channel, probe.type, probe.payload, probe.title)
                heyActionStatus = "Опрос: ${index}/${list.size} — ${probe.title}"
                ui.postDelayed(this, 450)
            }
        }
        ui.postDelayed(step, 150)
    }

    private fun copyHeyLog() {
        val text = buildString {
            appendLine("BlueLink · журнал протокола очков")
            appendLine("Устройство: ${connName.ifBlank { "—" }} (${connAddress.ifBlank { "—" }})")
            appendLine("Версия: ${appVersion()} (${appVersionCode()})")
            appendLine("Заряд: ${heyBattery?.let { "$it%" } ?: "нет данных"}")
            appendLine("Последний ответ: ${heyLastResponse.ifBlank { "—" }}")
            appendLine()
            logs.forEach { appendLine(it) }
        }
        val cm = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        cm.setPrimaryClip(ClipData.newPlainText("BlueLink", text))
        toast("Журнал скопирован — вставьте его в чат")
    }

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
        logHead.addView(pill("Копировать", false) { copyLog() })
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
        const val NO_CREDS_TEXT =
            "Очки не прислали имя своей Wi-Fi-сети. Это бывает, если прошивка держит его в секрете: " +
                "тогда подключитесь к сети очков вручную в настройках Wi-Fi, вернитесь сюда и нажмите «Забрать по Wi-Fi»."

        const val TAB_SCAN = "scan"
        const val TAB_DEVICE = "device"
        const val TAB_CAMERA = "camera"
        const val TAB_GATT = "gatt"
        const val TAB_PROFILES = "profiles"
        const val TAB_PHOTOS = "photos"
        const val TAB_CONSOLE = "console"
        const val TAB_REPORT = "report"
        const val TAB_HEY = "hey"

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
            TAB_CONSOLE to "⌨️ Консоль",
            TAB_HEY to "🕶 Очки"
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


