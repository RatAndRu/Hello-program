package com.example.bluelink

import android.Manifest
import android.annotation.SuppressLint
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCallback
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothGattDescriptor
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothProfile
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import androidx.core.content.ContextCompat
import java.util.UUID

/** Найденное устройство в списке. */
data class ScanItem(
    val name: String,
    val address: String,
    val rssi: Int,
    val device: BluetoothDevice?,
    val demo: Boolean = false,
    /** Устройство классического Bluetooth (наушники/колонка/автомагнитола) из списка сопряжённых. */
    val classic: Boolean = false,
    val serviceUuids: List<UUID> = emptyList(),
    /** Данные производителя из рекламного пакета: часто содержат модель/протокол. */
    val manufacturerData: Map<Int, ByteArray> = emptyMap(),
    val txPower: Int = Int.MIN_VALUE,
    val bondState: Int = BluetoothDevice.BOND_NONE,
    val deviceType: Int = BluetoothDevice.DEVICE_TYPE_UNKNOWN
) {
    val label: String get() = name.ifBlank { "Без имени" }
}

enum class ConnState { IDLE, CONNECTING, CONNECTED, DISCONNECTED }

interface BleListener {
    fun onScan(list: List<ScanItem>)
    fun onScanState(scanning: Boolean, message: String?)
    fun onConnection(state: ConnState, name: String, address: String)
    fun onServices(services: List<GattServiceInfo>)
    fun onCharValue(service: UUID, char: UUID, value: ByteArray)
    fun onCharWritten(service: UUID, char: UUID, ok: Boolean)
    fun onLog(line: String)
}

/**
 * Центральное устройство BLE: скан, подключение, чтение/запись/подписка на характеристики.
 *
 * Важно: колбэки Android Bluetooth приходят в служебных потоках, поэтому все события наружу
 * отдаются через главный поток — иначе интерфейс может «развалиться» или остаться пустым.
 */
class BleCentral(private val ctx: Context) {

    var listener: BleListener? = null

    private val main = Handler(Looper.getMainLooper())
    private var scanner: android.bluetooth.le.BluetoothLeScanner? = null

    private val found = LinkedHashMap<String, ScanItem>()
    private var lastUiPush = 0L
    private var pushScheduled = false

    private var gatt: BluetoothGatt? = null
    private val values = HashMap<String, ByteArray>()

    // Android разрешает только одну GATT-операцию за раз: подписки ставим в очередь,
    // иначе вторая подряд запись дескриптора молча теряется (и канал остаётся немым).
    // В очереди лежит тройка: сервис, характеристика и номер её вхождения.
    // Номер нужен там, где UUID повторяется — например, у HID-отчётов (2A4D).

    var services: List<GattServiceInfo> = emptyList()
        private set
    var connectedName: String = ""
        private set
    var connectedAddress: String = ""
        private set
    var connectedDevice: BluetoothDevice? = null
        private set
    var mtu: Int = 23
        private set

    /** Результаты операций: "read|svc|char" -> GATT-статус. По ним видно, нужно ли сопряжение/шифрование. */
    val opStatus = LinkedHashMap<String, Int>()

    /** Последние прочитанные значения характеристик. */
    fun valueOf(service: UUID, char: UUID): ByteArray? = values["$service|$char"]

    /** Последнее полученное уведомление по характеристике. */
    private val lastNotify = HashMap<String, ByteArray>()
    fun lastNotification(service: UUID, char: UUID): ByteArray? = lastNotify["$service|$char"]

    /** Транспорт текущего/последнего соединения: LE, BREDR, AUTO. */
    var transportLabel: String = ""
        private set

    /** Последняя причина неудачи — показывается в интерфейсе, а не только в журнале. */
    var lastError: String = ""
        private set

    private var connectItem: ScanItem? = null
    private var attemptIndex = 0
    private var connectedOnce = false
    private var servicesReceived = false
    private var discoveryRetries = 0

    private val connectTimeout = Runnable {
        if (!connectedOnce) {
            lastError = "Устройство не отвечает: соединение не установилось за 15 секунд."
            emit { it.onLog("Таймаут подключения (${transportLabel})") }
            tryNextTransportOrFail("таймаут")
        }
    }

    private val discoveryTimeout = Runnable {
        if (connectedOnce && !servicesReceived) {
            lastError = "Соединение есть, но устройство не отдало список сервисов."
            emit { it.onLog("Сервисы не пришли за 12 секунд — попробуйте «Переподключиться»") }
            emit { it.onServices(emptyList()) }
        }
    }

    val adapter: BluetoothAdapter?
        get() = (ctx.getSystemService(Context.BLUETOOTH_SERVICE) as? BluetoothManager)?.adapter

    fun isSupported(): Boolean = adapter != null

    fun isEnabled(): Boolean = try {
        adapter?.isEnabled == true
    } catch (e: SecurityException) {
        false
    }

    private fun emit(block: (BleListener) -> Unit) {
        if (Looper.myLooper() == Looper.getMainLooper()) {
            listener?.let(block)
        } else {
            main.post { listener?.let(block) }
        }
    }

    // ---------- Разрешения ----------

    fun requiredPermissions(): Array<String> {
        return if (Build.VERSION.SDK_INT >= 31) {
            arrayOf(
                Manifest.permission.BLUETOOTH_SCAN,
                Manifest.permission.BLUETOOTH_CONNECT
            )
        } else {
            arrayOf(
                Manifest.permission.ACCESS_FINE_LOCATION,
                Manifest.permission.ACCESS_COARSE_LOCATION
            )
        }
    }

    fun missingPermissions(): List<String> =
        requiredPermissions().filter {
            ContextCompat.checkSelfPermission(ctx, it) != PackageManager.PERMISSION_GRANTED
        }

    fun hasPermissions(): Boolean = missingPermissions().isEmpty()

    // ---------- Скан ----------

    @SuppressLint("MissingPermission")
    fun startScan() {
        if (!isSupported()) {
            emit { it.onScanState(false, "На этом телефоне нет Bluetooth") }
            return
        }
        if (!hasPermissions()) {
            emit { it.onScanState(false, "Нужны разрешения Bluetooth") }
            return
        }
        if (!isEnabled()) {
            emit { it.onScanState(false, "Bluetooth выключен") }
            return
        }
        val a = adapter ?: return
        scanner = a.bluetoothLeScanner
        if (scanner == null) {
            emit { it.onScanState(false, "Сканер BLE недоступен") }
            return
        }
        found.clear()
        emit { it.onScanState(true, null) }

        // Пары из системных настроек: часть устройств (наушники, часы) видна только так.
        try {
            for (d in a.bondedDevices ?: emptySet()) {
                addItem(
                    ScanItem(
                        name = safeName(d),
                        address = d.address,
                        rssi = 0,
                        device = d,
                        classic = true,
                        bondState = safeBondState(d),
                        deviceType = safeDeviceType(d)
                    )
                )
            }
        } catch (ignored: Exception) {
        }

        val settings = ScanSettings.Builder()
            .setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY)
            .build()
        try {
            scanner?.startScan(null, settings, callback)
        } catch (e: Exception) {
            emit { it.onScanState(false, "Не удалось запустить скан: ${e.message}") }
        }
        main.postDelayed(stopScanRunnable, 20_000)
    }

    private val stopScanRunnable = Runnable { stopScan() }

    @SuppressLint("MissingPermission")
    fun stopScan() {
        main.removeCallbacks(stopScanRunnable)
        try {
            scanner?.stopScan(callback)
        } catch (ignored: Exception) {
        }
        scanner = null
        emit { it.onScanState(false, null) }
    }

    private val callback = object : ScanCallback() {
        @SuppressLint("MissingPermission")
        override fun onScanResult(callbackType: Int, result: ScanResult) {
            val device = result.device ?: return
            val recordName = result.scanRecord?.deviceName
            val record = result.scanRecord
            val manufacturer = LinkedHashMap<Int, ByteArray>()
            try {
                val data = record?.manufacturerSpecificData
                if (data != null) {
                    for (i in 0 until data.size()) {
                        val id = data.keyAt(i)
                        manufacturer[id] = data.valueAt(i) ?: ByteArray(0)
                    }
                }
            } catch (ignored: Exception) {
            }
            val item = ScanItem(
                name = recordName ?: safeName(device).ifBlank { "" },
                address = device.address,
                rssi = result.rssi,
                device = device,
                serviceUuids = record?.serviceUuids?.map { it.uuid } ?: emptyList(),
                manufacturerData = manufacturer,
                txPower = record?.txPowerLevel ?: Int.MIN_VALUE,
                bondState = safeBondState(device),
                deviceType = safeDeviceType(device)
            )
            addItem(item)
        }

        override fun onBatchScanResults(results: MutableList<ScanResult>) {
            for (r in results) onScanResult(ScanSettings.CALLBACK_TYPE_ALL_MATCHES, r)
        }

        override fun onScanFailed(errorCode: Int) {
            emit { it.onScanState(false, "Скан прерван (код $errorCode)") }
        }
    }

    private fun addItem(item: ScanItem) {
        val existing = found[item.address]
        found[item.address] =
            if (existing == null) item
            else existing.copy(
                name = item.name.ifBlank { existing.name },
                rssi = if (item.rssi != 0) item.rssi else existing.rssi,
                device = item.device ?: existing.device,
                // Устройство реально ответило по BLE — значит, оно не только «классическое».
                classic = existing.classic && item.rssi == 0 && item.serviceUuids.isEmpty(),
                serviceUuids = if (item.serviceUuids.isNotEmpty()) item.serviceUuids else existing.serviceUuids,
                manufacturerData = if (item.manufacturerData.isNotEmpty()) item.manufacturerData else existing.manufacturerData,
                txPower = if (item.txPower != Int.MIN_VALUE) item.txPower else existing.txPower,
                bondState = item.bondState,
                deviceType = if (item.deviceType != BluetoothDevice.DEVICE_TYPE_UNKNOWN) item.deviceType else existing.deviceType
            )
        scheduleUiPush()
    }

    /** Не дёргаем интерфейс на каждый пакет: склеиваем обновления раз в 400 мс. */
    private fun scheduleUiPush() {
        val now = System.currentTimeMillis()
        if (pushScheduled) return
        val delay = (400 - (now - lastUiPush)).coerceAtLeast(0)
        pushScheduled = true
        main.postDelayed({
            pushScheduled = false
            lastUiPush = System.currentTimeMillis()
            val list = found.values.sortedWith(
                compareByDescending<ScanItem> { it.rssi }
                    .thenBy { it.label.lowercase() }
            )
            emit { it.onScan(list) }
        }, delay)
    }

    @SuppressLint("MissingPermission")
    private fun safeBondState(device: BluetoothDevice): Int = try {
        device.bondState
    } catch (e: SecurityException) {
        BluetoothDevice.BOND_NONE
    }

    @SuppressLint("MissingPermission")
    private fun safeDeviceType(device: BluetoothDevice): Int = try {
        device.type
    } catch (e: SecurityException) {
        BluetoothDevice.DEVICE_TYPE_UNKNOWN
    }

    @SuppressLint("MissingPermission")
    private fun safeName(device: BluetoothDevice): String = try {
        device.name ?: ""
    } catch (e: SecurityException) {
        ""
    }

    // ---------- Подключение ----------

    /**
     * Порядок попыток: сначала Low Energy, затем автоопределение (часто единственный способ
     * для наушников и колонок, которые уже сопряжены через классический Bluetooth).
     */
    private val transports: List<Pair<Int, String>> = buildList {
        add(BluetoothDevice.TRANSPORT_LE to "LE")
        if (Build.VERSION.SDK_INT >= 23) add(BluetoothDevice.TRANSPORT_AUTO to "AUTO")
        if (Build.VERSION.SDK_INT >= 23) add(BluetoothDevice.TRANSPORT_BREDR to "BREDR")
    }

    @SuppressLint("MissingPermission")
    fun connect(item: ScanItem) {
        if (!hasPermissions()) {
            emit { it.onLog("Нет разрешения BLUETOOTH_CONNECT") }
            return
        }
        val device = item.device
        if (device == null) {
            lastError = "Устройство не найдено — запустите скан заново."
            emit { it.onLog(lastError) }
            emit { it.onConnection(ConnState.DISCONNECTED, item.label, item.address) }
            return
        }
        closeGatt()
        connectItem = item
        attemptIndex = 0
        connectedOnce = false
        servicesReceived = false
        discoveryRetries = 0
        lastError = ""
        values.clear()
        connectedName = item.label
        connectedAddress = item.address
        connectedDevice = device
        transportLabel = ""
        startAttempt()
    }

    /** Переподключение к тому же устройству — лечит «залипший» GATT. */
    fun reconnect() {
        val item = connectItem
        if (item == null) {
            emit { it.onLog("Нет устройства для переподключения") }
            return
        }
        emit { it.onLog("Переподключение к ${item.label}…") }
        connect(item)
    }

    @SuppressLint("MissingPermission")
    private fun startAttempt() {
        val item = connectItem ?: return
        val device = item.device ?: return
        if (attemptIndex >= transports.size) {
            fail("Не удалось установить соединение")
            return
        }
        val (mode, name) = transports[attemptIndex]
        transportLabel = name
        services = emptyList()
        emit { it.onConnection(ConnState.CONNECTING, item.label, item.address) }
        emit {
            it.onLog(
                "Подключаюсь к ${item.label} (${item.address}), транспорт $name" +
                    if (attemptIndex > 0) " — попытка ${attemptIndex + 1}" else ""
            )
        }
        try {
            gatt = device.connectGatt(ctx, false, gattCallback, mode)
        } catch (e: Exception) {
            emit { it.onLog("Ошибка подключения ($name): ${e.message}") }
            gatt = null
        }
        if (gatt == null) {
            attemptIndex += 1
            main.postDelayed({ startAttempt() }, 300)
            return
        }
        main.removeCallbacks(connectTimeout)
        main.postDelayed(connectTimeout, 15_000)
    }

    @SuppressLint("MissingPermission")
    private fun tryNextTransportOrFail(reason: String) {
        main.removeCallbacks(connectTimeout)
        closeGatt()
        if (!connectedOnce && attemptIndex + 1 < transports.size) {
            attemptIndex += 1
            emit { it.onLog("Не вышло ($reason), пробую другой транспорт…") }
            main.postDelayed({ startAttempt() }, 500)
        } else {
            fail(reason)
        }
    }

    private fun fail(reason: String) {
        main.removeCallbacks(connectTimeout)
        main.removeCallbacks(discoveryTimeout)
        closeGatt()
        if (lastError.isEmpty()) lastError = reason
        emit { it.onLog("Подключение не удалось: $reason") }
        emit { it.onConnection(ConnState.DISCONNECTED, connectedName, connectedAddress) }
    }

    @SuppressLint("MissingPermission")
    private fun closeGatt() {
        val g = gatt
        gatt = null
        deniedSubscriptions.clear()
        synchronized(subscribedKeys) { subscribedKeys.clear() }
        synchronized(opQueue) {
            opQueue.clear()
            opBusy = false
        }
        main.removeCallbacks(opTimeout)
        try {
            g?.disconnect()
            g?.close()
        } catch (ignored: Exception) {
        }
    }

    @SuppressLint("MissingPermission")
    fun disconnect() {
        main.removeCallbacks(connectTimeout)
        main.removeCallbacks(discoveryTimeout)
        val had = gatt != null
        connectItem = null
        closeGatt()
        if (had) emit { it.onLog("Отключено") }
        emit { it.onConnection(ConnState.DISCONNECTED, connectedName, connectedAddress) }
    }

    /** Перечитать список сервисов (после смены профиля или «зависшего» GATT). */
    @SuppressLint("MissingPermission")
    fun refreshServices() {
        val g = gatt
        if (g == null) {
            emit { it.onLog("Нет соединения — нужно подключиться заново") }
            return
        }
        servicesReceived = false
        discoveryRetries = 0
        main.removeCallbacks(discoveryTimeout)
        main.postDelayed(discoveryTimeout, 12_000)
        try {
            if (!g.discoverServices()) {
                emit { it.onLog("Устройство отказало в чтении сервисов") }
            }
        } catch (e: Exception) {
            emit { it.onLog("Не удалось перечитать сервисы: ${e.message}") }
        }
    }

    private fun key(service: UUID, char: UUID) = "$service|$char"

    @SuppressLint("MissingPermission")
    private fun buildServices(g: BluetoothGatt): List<GattServiceInfo> {
        val out = ArrayList<GattServiceInfo>()
        for (s in g.services ?: emptyList()) {
            val chars = ArrayList<GattCharInfo>()
            for (c in s.characteristics ?: emptyList()) {
                chars.add(
                    GattCharInfo(
                        c.uuid,
                        c.properties,
                        values[key(s.uuid, c.uuid)],
                        c.descriptors?.map { it.uuid } ?: emptyList()
                    )
                )
            }
            out.add(GattServiceInfo(s.uuid, chars))
        }
        return out
    }

    private val gattCallback = object : BluetoothGattCallback() {

        @SuppressLint("MissingPermission")
        override fun onConnectionStateChange(g: BluetoothGatt, status: Int, newState: Int) {
            if (newState == BluetoothProfile.STATE_CONNECTED) {
                if (gatt !== g) {
                    // пришёл колбэк от старого соединения после переподключения — игнорируем
                    try {
                        g.close()
                    } catch (ignored: Exception) {
                    }
                    return
                }
                connectedOnce = true
                servicesReceived = false
                main.removeCallbacks(connectTimeout)
                emit { it.onLog("Соединение установлено ($transportLabel), читаю сервисы…") }
                emit { it.onConnection(ConnState.CONNECTED, connectedName, connectedAddress) }
                main.removeCallbacks(discoveryTimeout)
                main.postDelayed(discoveryTimeout, 12_000)
                try {
                    if (!g.discoverServices()) {
                        emit { it.onLog("Устройство не ответило на запрос сервисов") }
                    }
                } catch (e: Exception) {
                    emit { it.onLog("discoverServices: ${e.message}") }
                }
            } else if (newState == BluetoothProfile.STATE_DISCONNECTED) {
                main.removeCallbacks(connectTimeout)
                main.removeCallbacks(discoveryTimeout)
                if (!connectedOnce) {
                    emit { it.onLog("Соединение отклонено (status=$status, транспорт $transportLabel)") }
                    if (gatt === g) {
                        gatt = null
                        try {
                            g.close()
                        } catch (ignored: Exception) {
                        }
                    }
                    attemptIndex += 1
                    if (attemptIndex < transports.size) {
                        main.postDelayed({ startAttempt() }, 500)
                    } else {
                        val hint = when (status) {
                            133 -> "Устройство отклонило подключение (133)."
                            8 -> "Устройство вне зоны или уже занято."
                            257 -> "Устройство не поддерживает такой тип соединения."
                            else -> "Соединение не установлено (status=$status)."
                        }
                        fail(hint)
                    }
                    return
                }
                emit { it.onLog("Устройство отключилось (status=$status)") }
                emit { it.onConnection(ConnState.DISCONNECTED, connectedName, connectedAddress) }
                if (gatt === g) {
                    gatt = null
                    try {
                        g.close()
                    } catch (ignored: Exception) {
                    }
                }
            }
        }

        override fun onServicesDiscovered(g: BluetoothGatt, status: Int) {
            if (status != BluetoothGatt.GATT_SUCCESS) {
                emit { it.onLog("Сервисы не прочитаны (status=$status)") }
                return
            }
            main.removeCallbacks(discoveryTimeout)
            val discovered = buildServices(g)
            if (discovered.isEmpty() && discoveryRetries < 2) {
                // Часть устройств отдаёт GATT-таблицу только со второго запроса.
                discoveryRetries += 1
                emit { it.onLog("Устройство вернуло пустую таблицу — запрашиваю сервисы ещё раз (${discoveryRetries}/2)") }
                main.postDelayed({
                    try {
                        g.discoverServices()
                    } catch (e: Exception) {
                        emit { it.onLog("Повторный запрос сервисов: ${e.message}") }
                    }
                }, 1200L * discoveryRetries)
                return
            }
            servicesReceived = true
            services = discovered
            emit { it.onServices(services) }
            emit { it.onLog("Сервисов найдено: ${services.size}, характеристик: ${services.sumOf { it.chars.size }}") }
            if (services.isEmpty()) {
                lastError = "Устройство не отдало ни одного сервиса. Возможно, оно требует сопряжения " +
                    "или работает только по классическому Bluetooth."
                emit { it.onLog(lastError) }
            }
            try {
                g.requestMtu(247)
            } catch (ignored: Exception) {
            }
        }

        override fun onDescriptorWrite(
            g: BluetoothGatt,
            descriptor: BluetoothGattDescriptor,
            status: Int
        ) {
            val ch = descriptor.characteristic
            val svc = ch?.service?.uuid ?: UUID(0L, 0L)
            val charUuid = ch?.uuid ?: UUID(0L, 0L)
            opStatus["notify|$svc|$charUuid"] = status
            emit {
                it.onLog(
                    if (status == BluetoothGatt.GATT_SUCCESS) "Подписка включена: ${GattNames.uuidLabel(charUuid)}"
                    else "Подписка не удалась: статус ${GattNames.gattStatusText(status)}"
                )
            }
            finishOp()
        }

        override fun onMtuChanged(g: BluetoothGatt, newMtu: Int, status: Int) {
            mtu = newMtu
            emit { it.onLog("MTU: $newMtu байт") }
            if (services.isEmpty() && discoveryRetries < 2) {
                discoveryRetries += 1
                emit { it.onLog("Сервисы ещё пусты — повторный запрос после MTU") }
                main.postDelayed({
                    try {
                        g.discoverServices()
                    } catch (ignored: Exception) {
                    }
                }, 800)
            }
        }

        // --- API 33+ ---
        override fun onCharacteristicRead(
            g: BluetoothGatt,
            characteristic: BluetoothGattCharacteristic,
            value: ByteArray,
            status: Int
        ) {
            handleRead(g, characteristic, value, status)
        }

        // --- API < 33 ---
        @Deprecated("Deprecated in API 33")
        override fun onCharacteristicRead(
            g: BluetoothGatt,
            characteristic: BluetoothGattCharacteristic,
            status: Int
        ) {
            val value = characteristic.value ?: ByteArray(0)
            handleRead(g, characteristic, value, status)
        }

        override fun onCharacteristicChanged(
            g: BluetoothGatt,
            characteristic: BluetoothGattCharacteristic,
            value: ByteArray
        ) {
            handleNotify(characteristic, value)
        }

        @Deprecated("Deprecated in API 33")
        override fun onCharacteristicChanged(
            g: BluetoothGatt,
            characteristic: BluetoothGattCharacteristic
        ) {
            handleNotify(characteristic, characteristic.value ?: ByteArray(0))
        }

        override fun onCharacteristicWrite(
            g: BluetoothGatt,
            characteristic: BluetoothGattCharacteristic,
            status: Int
        ) {
            val ok = status == BluetoothGatt.GATT_SUCCESS
            val svc = characteristic.service?.uuid ?: UUID(0L, 0L)
            opStatus["write|$svc|${characteristic.uuid}"] = status
            emit { it.onCharWritten(svc, characteristic.uuid, ok) }
            emit {
                it.onLog(
                    if (ok) "Записано в ${GattNames.uuidLabel(characteristic.uuid)}"
                    else "Ошибка записи (status=$status)"
                )
            }
            finishOp()
        }
    }

    private fun serviceOf(char: BluetoothGattCharacteristic): UUID =
        char.service?.uuid ?: UUID.fromString("00000000-0000-0000-0000-000000000000")

    private fun handleRead(
        g: BluetoothGatt,
        characteristic: BluetoothGattCharacteristic,
        value: ByteArray,
        status: Int
    ) {
        opStatus["read|${serviceOf(characteristic)}|${characteristic.uuid}"] = status
        finishOp()
        if (status != BluetoothGatt.GATT_SUCCESS) {
            emit { it.onLog("Чтение не удалось (status=$status)") }
            return
        }
        val svc = serviceOf(characteristic)
        values[key(svc, characteristic.uuid)] = value
        services = buildServices(g)
        emit { it.onServices(services) }
        emit { it.onCharValue(svc, characteristic.uuid, value) }
    }

    private fun handleNotify(characteristic: BluetoothGattCharacteristic, value: ByteArray) {
        val svc = serviceOf(characteristic)
        lastNotify["$svc|${characteristic.uuid}"] = value
        values[key(svc, characteristic.uuid)] = value
        emit { it.onCharValue(svc, characteristic.uuid, value) }
    }

    // ---------- Операции с характеристиками ----------

    @SuppressLint("MissingPermission")
    private fun characteristic(service: UUID?, char: UUID, index: Int = 0): BluetoothGattCharacteristic? {
        val g = gatt ?: return null
        var seen = 0
        for (s in g.services ?: emptyList()) {
            if (service != null && s.uuid != service) continue
            for (c in s.characteristics ?: emptyList()) {
                if (c.uuid != char) continue
                if (seen == index) return c
                seen += 1
            }
        }
        return null
    }

    // ---------- Очередь операций GATT ----------
    //
    // Android выполняет операции GATT строго по одной. Если отправить вторую,
    // пока первая не завершилась, вызов возвращает ошибку — именно так в 2.3.1
    // все команды очкам получали «запись не принята», хотя связь была жива.
    // Поэтому все чтения, записи и подписки идут через одну очередь, а каждая
    // операция завершается по своему обратному вызову или по таймауту.

    private enum class OpKind { SUBSCRIBE, UNSUBSCRIBE, READ, WRITE }

    private data class GattOp(
        val kind: OpKind,
        val service: UUID?,
        val char: UUID,
        val index: Int,
        val payload: ByteArray?,
        val withResponse: Boolean?,
        val title: String
    )

    private val opQueue = ArrayDeque<GattOp>()
    private val subscribedKeys = HashSet<String>()
    private var opBusy = false
    private var opStartedAt = 0L
    private var opTitle = ""
    private val opTimeout = Runnable { opTimedOut() }

    private fun enqueue(op: GattOp) {
        synchronized(opQueue) { opQueue.addLast(op) }
        pumpOps()
    }

    private fun pumpOps() {
        val next: GattOp
        synchronized(opQueue) {
            if (opBusy) return
            next = opQueue.removeFirstOrNull() ?: return
            opBusy = true
        }
        opStartedAt = System.currentTimeMillis()
        opTitle = next.title
        val started = runOp(next)
        if (!started) {
            finishOp()
            return
        }
        main.removeCallbacks(opTimeout)
        main.postDelayed(opTimeout, 2000)
    }

    private fun finishOp() {
        main.removeCallbacks(opTimeout)
        synchronized(opQueue) { opBusy = false }
        main.postDelayed({ pumpOps() }, 60)
    }

    private fun opTimedOut() {
        val was = synchronized(opQueue) {
            val v = opBusy
            opBusy = false
            v
        }
        if (!was) return
        emit { it.onLog("Связь: операция «$opTitle» не ответила за 2 с — иду дальше") }
        main.postDelayed({ pumpOps() }, 60)
    }

    /** Сколько операций ждёт выполнения. */
    val pendingOps: Int
        get() = synchronized(opQueue) { opQueue.size + if (opBusy) 1 else 0 }

    @SuppressLint("MissingPermission")
    private fun runOp(op: GattOp): Boolean {
        val g = gatt ?: run {
            emit { it.onLog("Нет соединения") }
            return false
        }
        val c = characteristic(op.service, op.char, op.index) ?: run {
            emit { it.onLog("Нет характеристики ${GattNames.uuidLabel(op.char)}") }
            return false
        }
        return try {
            when (op.kind) {
                OpKind.SUBSCRIBE, OpKind.UNSUBSCRIBE -> {
                    val enable = op.kind == OpKind.SUBSCRIBE
                    g.setCharacteristicNotification(c, enable)
                    val descriptor = c.getDescriptor(
                        UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")
                    )
                    if (descriptor == null) {
                        if (enable) emit { it.onLog("Подписка включена: ${GattNames.uuidLabel(c.uuid)}") }
                        finishOp()
                        return true
                    }
                    val value = when {
                        !enable -> BluetoothGattDescriptor.DISABLE_NOTIFICATION_VALUE
                        (c.properties and BluetoothGattCharacteristic.PROPERTY_INDICATE) != 0 ->
                            BluetoothGattDescriptor.ENABLE_INDICATION_VALUE
                        else -> BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE
                    }
                    if (Build.VERSION.SDK_INT >= 33) {
                        g.writeDescriptor(descriptor, value)
                    } else {
                        descriptor.value = value
                        @Suppress("DEPRECATION")
                        g.writeDescriptor(descriptor)
                    }
                    true
                }
                OpKind.READ -> g.readCharacteristic(c)
                OpKind.WRITE -> {
                    val payload = op.payload ?: ByteArray(0)
                    val supportsResponse =
                        (c.properties and BluetoothGattCharacteristic.PROPERTY_WRITE) != 0
                    val type = when {
                        op.withResponse == true -> BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT
                        op.withResponse == false -> BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE
                        supportsResponse -> BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT
                        else -> BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE
                    }
                    if (Build.VERSION.SDK_INT >= 33) {
                        g.writeCharacteristic(c, payload, type) ==
                            android.bluetooth.BluetoothStatusCodes.SUCCESS
                    } else {
                        c.writeType = type
                        c.value = payload
                        @Suppress("DEPRECATION")
                        g.writeCharacteristic(c)
                    }
                }
            }
        } catch (e: Exception) {
            emit { it.onLog("Операция «${op.title}»: ${e.message}") }
            val message = e.message ?: ""
            if (message.contains("PRIVILEGED", ignoreCase = true)) {
                deniedSubscriptions.add("${op.service}|${op.char}")
            }
            false
        }
    }

    /** Характеристики, на которые система не дала подписаться: второй раз не пробуем. */
    private val deniedSubscriptions = HashSet<String>()

    fun wasDenied(service: UUID?, char: UUID): Boolean =
        deniedSubscriptions.contains("$service|$char")

    fun read(service: UUID?, char: UUID): Boolean {
        if (gatt == null) {
            emit { it.onLog("Нет соединения") }
            return false
        }
        enqueue(GattOp(OpKind.READ, service, char, 0, null, null, "чтение"))
        return true
    }

    /**
     * Запись ставится в очередь и выполняется, когда освободится GATT.
     * Возвращает true, если запись принята в очередь (результат — в журнале).
     */
    fun write(service: UUID?, char: UUID, payload: ByteArray, withResponse: Boolean? = null): Boolean {
        if (gatt == null) {
            emit { it.onLog("Нет соединения") }
            return false
        }
        enqueue(GattOp(OpKind.WRITE, service, char, 0, payload, withResponse, "запись"))
        return true
    }

    /** Подписка тоже идёт через очередь — без дублей и без блокировки команд. */
    fun subscribe(service: UUID?, char: UUID, enable: Boolean = true, index: Int = 0): Boolean {
        if (gatt == null) {
            emit { it.onLog("Нет соединения") }
            return false
        }
        val key = "$service|$char|$index|$enable"
        synchronized(subscribedKeys) {
            if (!subscribedKeys.add(key)) return true
        }
        enqueue(
            GattOp(
                if (enable) OpKind.SUBSCRIBE else OpKind.UNSUBSCRIBE,
                service, char, index, null, null,
                if (enable) "подписка" else "отписка"
            )
        )
        return true
    }

    /**
     * Раньше здесь был флаг «идёт подписка». Теперь очередь одна на всё,
     * поэтому отдельная блокировка команд не нужна.
     */
    val busySubscribing: Boolean
        get() = false

    /** Состояние сопряжения с текущим устройством. */
    @SuppressLint("MissingPermission")
    fun bondState(): Int = try {
        connectedDevice?.bondState ?: BluetoothDevice.BOND_NONE
    } catch (e: SecurityException) {
        BluetoothDevice.BOND_NONE
    }

    fun bondStateText(): String = when (bondState()) {
        BluetoothDevice.BOND_BONDED -> "сопряжено"
        BluetoothDevice.BOND_BONDING -> "идёт сопряжение"
        else -> "не сопряжено"
    }

    /** Запускает системное сопряжение — многим очкам оно нужно до обмена данными. */
    @SuppressLint("MissingPermission")
    fun createBond(): Boolean {
        val device = connectedDevice ?: run {
            emit { it.onLog("Нет устройства для сопряжения") }
            return false
        }
        return try {
            val started = device.createBond()
            emit { it.onLog(if (started) "Запущено сопряжение с ${device.address}" else "Сопряжение не запустилось") }
            started
        } catch (e: Exception) {
            emit { it.onLog("Сопряжение: ${e.message}") }
            false
        }
    }

    /**
     * SDP-опрос: какие каналы/профили устройство объявляет по классическому Bluetooth
     * (SPP, A2DP, HFP, HID, OBEX…). Для закрытых очков это иногда единственный видимый след.
     */
    @SuppressLint("MissingPermission")
    fun fetchSdpProfiles(done: (List<UUID>) -> Unit) {
        val device = connectedDevice ?: connectItem?.device
        if (device == null) {
            emit { it.onLog("SDP: устройство не выбрано") }
            done(emptyList())
            return
        }
        val already = try {
            device.uuids?.map { it.uuid } ?: emptyList()
        } catch (e: SecurityException) {
            emptyList()
        }
        var finished = false
        val receiver = object : BroadcastReceiver() {
            override fun onReceive(c: Context?, intent: Intent?) {
                if (finished) return
                val fromIntent = try {
                    val d = if (Build.VERSION.SDK_INT >= 33) {
                        intent?.getParcelableExtra(BluetoothDevice.EXTRA_DEVICE, BluetoothDevice::class.java)
                    } else {
                        @Suppress("DEPRECATION")
                        intent?.getParcelableExtra(BluetoothDevice.EXTRA_DEVICE)
                    }
                    d
                } catch (e: Exception) {
                    null
                }
                if (fromIntent != null && fromIntent.address != device.address) return
                finished = true
                try {
                    ctx.unregisterReceiver(this)
                } catch (ignored: Exception) {
                }
                val list = parseUuidArray(intent) + already
                emit { it.onLog("SDP: профилей получено ${list.distinct().size}") }
                done(list.distinct())
            }
        }
        try {
            if (Build.VERSION.SDK_INT >= 33) {
                ctx.registerReceiver(receiver, IntentFilter(BluetoothDevice.ACTION_UUID), Context.RECEIVER_NOT_EXPORTED)
            } else {
                @Suppress("UnspecifiedRegisterReceiverFlag")
                ctx.registerReceiver(receiver, IntentFilter(BluetoothDevice.ACTION_UUID))
            }
            device.fetchUuidsWithSdp()
            emit { it.onLog("SDP: запрос профилей отправлен") }
        } catch (e: Exception) {
            emit { it.onLog("SDP: не удалось запустить (${e.message})") }
            finished = true
            try {
                ctx.unregisterReceiver(receiver)
            } catch (ignored: Exception) {
            }
            done(already)
            return
        }
        main.postDelayed({
            if (!finished) {
                finished = true
                try {
                    ctx.unregisterReceiver(receiver)
                } catch (ignored: Exception) {
                }
                emit { it.onLog("SDP: ответа нет, устройство не объявляет классических профилей") }
                done(already)
            }
        }, 5000)
    }

    @Suppress("DEPRECATION")
    private fun parseUuidArray(intent: Intent?): List<UUID> {
        val raw = try {
            if (Build.VERSION.SDK_INT >= 33) {
                intent?.getParcelableArrayExtra(BluetoothDevice.EXTRA_UUID, android.os.Parcelable::class.java)
            } else {
                intent?.getParcelableArrayExtra(BluetoothDevice.EXTRA_UUID)
            }
        } catch (e: Exception) {
            null
        }
        val list = ArrayList<UUID>()
        for (item in raw ?: emptyArray()) {
            try {
                val text = item.toString()
                UUID.fromString(text)?.let { list.add(it) }
            } catch (ignored: Exception) {
            }
        }
        return list
    }

    fun findServiceByShort(short: Int): UUID? =
        services.firstOrNull { GattNames.shortCode(it.uuid) == short }?.uuid

    fun hasChar(service: UUID?, char: UUID): Boolean = characteristic(service, char) != null
}
