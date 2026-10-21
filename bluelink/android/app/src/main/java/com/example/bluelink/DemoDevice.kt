package com.example.bluelink

import java.util.UUID

/**
 * Виртуальные умные очки: настоящее BLE-железо не нужно, но весь путь
 * «профиль → команда → снимок → галерея» работает ровно так же, как с реальным устройством.
 */
object DemoDevice {

    const val ADDRESS = "DEMO-00-00-00-00-01"

    val serviceBattery: UUID = parseUuid("180f")!!
    val charBattery: UUID = parseUuid("2a19")!!
    val serviceInfo: UUID = parseUuid("180a")!!
    val charModel: UUID = parseUuid("2a24")!!
    val charFirmware: UUID = parseUuid("2a26")!!
    val serviceCamera: UUID = parseUuid("ffe0")!!
    val charTrigger: UUID = parseUuid("ffe1")!!
    val charData: UUID = parseUuid("ffe2")!!

    fun isDemo(address: String?) = address == ADDRESS

    fun scanItem(): ScanItem = ScanItem(
        name = "Демо: умные очки RayX",
        address = ADDRESS,
        rssi = -42,
        device = null,
        demo = true,
        serviceUuids = listOf(serviceCamera, serviceBattery)
    )

    fun services(): List<GattServiceInfo> = listOf(
        GattServiceInfo(
            serviceBattery,
            listOf(
                GattCharInfo(charBattery, 0x12, byteArrayOf(78))
            )
        ),
        GattServiceInfo(
            serviceInfo,
            listOf(
                GattCharInfo(charModel, 0x02, "RayX Demo".toByteArray()),
                GattCharInfo(charFirmware, 0x02, "1.0.0-demo".toByteArray())
            )
        ),
        GattServiceInfo(
            serviceCamera,
            listOf(
                GattCharInfo(charTrigger, 0x08, null),
                GattCharInfo(charData, 0x10, null)
            )
        )
    )

    fun readValue(char: UUID): ByteArray? = when (char) {
        charBattery -> byteArrayOf(78)
        charModel -> "RayX Demo".toByteArray()
        charFirmware -> "1.0.0-demo".toByteArray()
        else -> null
    }
}
