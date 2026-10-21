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
import android.content.Context
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
    val classic: Boolean = false,
    val serviceUuids: List<UUID> = emptyList()
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
 * Один общий движок, через который работают и обзор GATT, и профили устройств.
 */
class BleCentral(private val ctx: Context) {

    var listener: BleListener? = null

    private val handler = Handler(Looper.getMainLooper())
    private var scanner: android.bluetooth.le.BluetoothLeScanner? = null

    private val found = LinkedHashMap<String, ScanItem>()
    private var lastUiPush = 0L
    private var pushScheduled = false

    private var gatt: BluetoothGatt? = null
    private val values = HashMap<String, ByteArray>()

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

    val adapter: BluetoothAdapter?
        get() = (ctx.getSystemService(Context.BLUETOOTH_SERVICE) as? BluetoothManager)?.adapter

    fun isSupported(): Boolean = adapter != null

    fun isEnabled(): Boolean = try {
        adapter?.isEnabled == true
    } catch (e: SecurityException) {
        false
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
            listener?.onScanState(false, "На этом телефоне нет Bluetooth")
            return
        }
        if (!hasPermissions()) {
            listener?.onScanState(false, "Нужны разрешения Bluetooth")
            return
        }
        if (!isEnabled()) {
            listener?.onScanState(false, "Bluetooth выключен")
            return
        }
        val a = adapter ?: return
        scanner = a.bluetoothLeScanner
        if (scanner == null) {
            listener?.onScanState(false, "Сканер BLE недоступен")
            return
        }
        found.clear()
        listener?.onScanState(true, null)

        // Пары из системных настроек: часть устройств (наушники, часы) видна только так.
        try {
            for (d in a.bondedDevices ?: emptySet()) {
                addItem(
                    ScanItem(
                        name = safeName(d),
                        address = d.address,
                        rssi = 0,
                        device = d,
                        classic = true
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
            listener?.onScanState(false, "Не удалось запустить скан: ${e.message}")
        }
        handler.postDelayed(stopScanRunnable, 20_000)
    }

    private val stopScanRunnable = Runnable { stopScan() }

    @SuppressLint("MissingPermission")
    fun stopScan() {
        handler.removeCallbacks(stopScanRunnable)
        try {
            scanner?.stopScan(callback)
        } catch (ignored: Exception) {
        }
        scanner = null
        listener?.onScanState(false, null)
    }

    private val callback = object : ScanCallback() {
        @SuppressLint("MissingPermission")
        override fun onScanResult(callbackType: Int, result: ScanResult) {
            val device = result.device ?: return
            val recordName = result.scanRecord?.deviceName
            val item = ScanItem(
                name = recordName ?: safeName(device).ifBlank { "" },
                address = device.address,
                rssi = result.rssi,
                device = device,
                serviceUuids = result.scanRecord?.serviceUuids?.map { it.uuid } ?: emptyList()
            )
            addItem(item)
        }

        override fun onBatchScanResults(results: MutableList<ScanResult>) {
            for (r in results) onScanResult(ScanSettings.CALLBACK_TYPE_ALL_MATCHES, r)
        }

        override fun onScanFailed(errorCode: Int) {
            listener?.onScanState(false, "Скан прерван (код $errorCode)")
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
                serviceUuids = if (item.serviceUuids.isNotEmpty()) item.serviceUuids else existing.serviceUuids
            )
        scheduleUiPush()
    }

    /** Не дёргаем интерфейс на каждый пакет: склеиваем обновления раз в 400 мс. */
    private fun scheduleUiPush() {
        val now = System.currentTimeMillis()
        if (pushScheduled) return
        val delay = (400 - (now - lastUiPush)).coerceAtLeast(0)
        pushScheduled = true
        handler.postDelayed({
            pushScheduled = false
            lastUiPush = System.currentTimeMillis()
            val list = found.values.sortedWith(
                compareByDescending<ScanItem> { it.rssi }
                    .thenBy { it.label.lowercase() }
            )
            listener?.onScan(list)
        }, delay)
    }

    @SuppressLint("MissingPermission")
    private fun safeName(device: BluetoothDevice): String = try {
        device.name ?: ""
    } catch (e: SecurityException) {
        ""
    }

    // ---------- Подключение ----------

    @SuppressLint("MissingPermission")
    fun connect(item: ScanItem) {
        if (!hasPermissions()) {
            listener?.onLog("Нет разрешения BLUETOOTH_CONNECT")
            return
        }
        disconnect()
        val device = item.device
        if (device == null) {
            listener?.onLog("Устройство не найдено — запустите скан заново")
            return
        }
        connectedName = item.label
        connectedAddress = item.address
        connectedDevice = device
        values.clear()
        listener?.onConnection(ConnState.CONNECTING, item.label, item.address)
        listener?.onLog("Подключаюсь к ${item.label} (${item.address})…")
        try {
            gatt = if (Build.VERSION.SDK_INT >= 23) {
                device.connectGatt(ctx, false, gattCallback, BluetoothDevice.TRANSPORT_LE)
            } else {
                device.connectGatt(ctx, false, gattCallback)
            }
        } catch (e: Exception) {
            listener?.onLog("Ошибка подключения: ${e.message}")
            listener?.onConnection(ConnState.DISCONNECTED, connectedName, connectedAddress)
        }
    }

    @SuppressLint("MissingPermission")
    fun disconnect() {
        val g = gatt ?: return
        gatt = null
        try {
            g.disconnect()
            g.close()
        } catch (ignored: Exception) {
        }
        listener?.onLog("Отключено")
        listener?.onConnection(ConnState.DISCONNECTED, connectedName, connectedAddress)
    }

    /** Перечитать список сервисов (после смены профиля или «зависшего» GATT). */
    @SuppressLint("MissingPermission")
    fun refreshServices() {
        val g = gatt ?: return
        try {
            g.discoverServices()
        } catch (e: Exception) {
            listener?.onLog("Не удалось перечитать сервисы: ${e.message}")
        }
    }

    private fun key(service: UUID, char: UUID) = "$service|$char"

    @SuppressLint("MissingPermission")
    private fun buildServices(g: BluetoothGatt): List<GattServiceInfo> {
        val out = ArrayList<GattServiceInfo>()
        for (s in g.services ?: emptyList()) {
            val chars = ArrayList<GattCharInfo>()
            for (c in s.characteristics ?: emptyList()) {
                chars.add(GattCharInfo(c.uuid, c.properties, values[key(s.uuid, c.uuid)]))
            }
            out.add(GattServiceInfo(s.uuid, chars))
        }
        return out
    }

    private val gattCallback = object : BluetoothGattCallback() {

        @SuppressLint("MissingPermission")
        override fun onConnectionStateChange(g: BluetoothGatt, status: Int, newState: Int) {
            if (newState == BluetoothProfile.STATE_CONNECTED) {
                listener?.onLog("Соединение установлено, читаю сервисы…")
                listener?.onConnection(ConnState.CONNECTED, connectedName, connectedAddress)
                try {
                    g.discoverServices()
                } catch (e: Exception) {
                    listener?.onLog("discoverServices: ${e.message}")
                }
            } else if (newState == BluetoothProfile.STATE_DISCONNECTED) {
                listener?.onLog("Устройство отключилось (status=$status)")
                listener?.onConnection(ConnState.DISCONNECTED, connectedName, connectedAddress)
                try {
                    g.close()
                } catch (ignored: Exception) {
                }
                if (gatt === g) gatt = null
            }
        }

        override fun onServicesDiscovered(g: BluetoothGatt, status: Int) {
            if (status != BluetoothGatt.GATT_SUCCESS) {
                listener?.onLog("Сервисы не прочитаны (status=$status)")
                return
            }
            services = buildServices(g)
            listener?.onServices(services)
            listener?.onLog("Сервисов найдено: ${services.size}")
            try {
                g.requestMtu(247)
            } catch (ignored: Exception) {
            }
        }

        override fun onMtuChanged(g: BluetoothGatt, newMtu: Int, status: Int) {
            mtu = newMtu
            listener?.onLog("MTU: $newMtu байт")
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
            listener?.onCharWritten(svc, characteristic.uuid, ok)
            listener?.onLog(if (ok) "Записано в ${GattNames.uuidLabel(characteristic.uuid)}"
            else "Ошибка записи (status=$status)")
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
        if (status != BluetoothGatt.GATT_SUCCESS) {
            listener?.onLog("Чтение не удалось (status=$status)")
            return
        }
        val svc = serviceOf(characteristic)
        values[key(svc, characteristic.uuid)] = value
        services = buildServices(g)
        listener?.onServices(services)
        listener?.onCharValue(svc, characteristic.uuid, value)
    }

    private fun handleNotify(characteristic: BluetoothGattCharacteristic, value: ByteArray) {
        val svc = serviceOf(characteristic)
        values[key(svc, characteristic.uuid)] = value
        listener?.onCharValue(svc, characteristic.uuid, value)
    }

    // ---------- Операции с характеристиками ----------

    @SuppressLint("MissingPermission")
    private fun characteristic(service: UUID?, char: UUID): BluetoothGattCharacteristic? {
        val g = gatt ?: return null
        for (s in g.services ?: emptyList()) {
            if (service != null && s.uuid != service) continue
            for (c in s.characteristics ?: emptyList()) {
                if (c.uuid == char) return c
            }
        }
        return null
    }

    @SuppressLint("MissingPermission")
    fun read(service: UUID?, char: UUID): Boolean {
        val g = gatt ?: run {
            listener?.onLog("Нет соединения")
            return false
        }
        val c = characteristic(service, char) ?: run {
            listener?.onLog("Нет характеристики ${GattNames.uuidLabel(char)}")
            return false
        }
        return try {
            g.readCharacteristic(c)
        } catch (e: Exception) {
            listener?.onLog("Чтение: ${e.message}")
            false
        }
    }

    @SuppressLint("MissingPermission")
    fun write(service: UUID?, char: UUID, payload: ByteArray, withResponse: Boolean? = null): Boolean {
        val g = gatt ?: run {
            listener?.onLog("Нет соединения")
            return false
        }
        val c = characteristic(service, char) ?: run {
            listener?.onLog("Нет характеристики ${GattNames.uuidLabel(char)}")
            return false
        }
        return try {
            val supportsResponse = (c.properties and BluetoothGattCharacteristic.PROPERTY_WRITE) != 0
            val type = when {
                withResponse == true -> BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT
                withResponse == false -> BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE
                supportsResponse -> BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT
                else -> BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE
            }
            if (Build.VERSION.SDK_INT >= 33) {
                // На API 33+ метод возвращает int-код (0 = SUCCESS), а не boolean.
                g.writeCharacteristic(c, payload, type) == android.bluetooth.BluetoothStatusCodes.SUCCESS
            } else {
                c.writeType = type
                c.value = payload
                @Suppress("DEPRECATION")
                g.writeCharacteristic(c)
            }
        } catch (e: Exception) {
            listener?.onLog("Запись: ${e.message}")
            false
        }
    }

    @SuppressLint("MissingPermission")
    fun subscribe(service: UUID?, char: UUID, enable: Boolean = true): Boolean {
        val g = gatt ?: run {
            listener?.onLog("Нет соединения")
            return false
        }
        val c = characteristic(service, char) ?: run {
            listener?.onLog("Нет характеристики ${GattNames.uuidLabel(char)}")
            return false
        }
        return try {
            g.setCharacteristicNotification(c, enable)
            val descriptor = c.getDescriptor(UUID.fromString("00002902-0000-1000-8000-00805f9b34fb"))
                ?: return enable
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
        } catch (e: Exception) {
            listener?.onLog("Подписка: ${e.message}")
            false
        }
    }

    fun findServiceByShort(short: Int): UUID? =
        services.firstOrNull { GattNames.shortCode(it.uuid) == short }?.uuid

    fun hasChar(service: UUID?, char: UUID): Boolean = characteristic(service, char) != null
}
