package com.example.bluelink

import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothProfile
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraManager
import android.media.session.MediaSession
import android.media.session.PlaybackState
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.view.InputDevice
import android.view.KeyEvent

/**
 * Кольцо как пульт.
 *
 * Почему так: кольцо с сервисом HID (0x1812) работает не «сам по себе», а как
 * устройство ввода телефона. Android подключает такие устройства к себе
 * (профиль HID Host) и превращает взмахи в обычные нажатия — чаще всего это
 * медиа-клавиши («следующий трек», «предыдущий», «пауза»), иногда стрелки или
 * громкость. Приложение не может «прочитать» HID-отчёты напрямую: подписка на
 * 2A4D требует системного разрешения BLUETOOTH_PRIVILEGED (это проверено на
 * Android 13 — журнал так и пишет). Зато эти нажатия видит вся система.
 *
 * Отсюда честный путь: перехватывать нажатия кольца на уровне телефона.
 * - Медиа-клавиши ловит MediaSession — работает и когда приложение свёрнуто.
 * - Остальные клавиши (стрелки, громкость) приходят в окно приложения, поэтому
 *   их ловит сам экран.
 *
 * Ничего не выдумываем: в журнал попадает код клавиши и scanCode, а не
 * «распознанный жест», если код не опознан.
 */
object RingControls {

    /** Что делать, когда кольцо нажали. */
    enum class Action(val id: String, val title: String) {
        NOTHING("nothing", "только записывать в журнал"),
        PHOTO("photo", "снимок на очках"),
        LED("led", "подсветка очков"),
        TORCH("torch", "фонарик телефона"),
        VIDEO("video", "запись видео на очках"),
        LOG("log", "фотография телефона (вкладка «Фото»)");

        companion object {
            fun byId(id: String?): Action = values().firstOrNull { it.id == id } ?: PHOTO
        }
    }

    data class Press(val keyCode: Int, val scanCode: Int, val action: Int, val source: String) {
        fun keyName(): String = KeyEvent.keyCodeToString(keyCode).removePrefix("KEYCODE_")

        fun human(): String = when (keyCode) {
            KeyEvent.KEYCODE_MEDIA_NEXT, KeyEvent.KEYCODE_MEDIA_FAST_FORWARD,
            KeyEvent.KEYCODE_DPAD_RIGHT, KeyEvent.KEYCODE_VOLUME_UP ->
                "свайп вперёд (влево-вправо)"
            KeyEvent.KEYCODE_MEDIA_PREVIOUS, KeyEvent.KEYCODE_MEDIA_REWIND,
            KeyEvent.KEYCODE_DPAD_LEFT, KeyEvent.KEYCODE_VOLUME_DOWN ->
                "свайп назад"
            KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE, KeyEvent.KEYCODE_MEDIA_PLAY,
            KeyEvent.KEYCODE_MEDIA_PAUSE, KeyEvent.KEYCODE_HEADSETHOOK,
            KeyEvent.KEYCODE_ENTER, KeyEvent.KEYCODE_DPAD_CENTER ->
                "нажатие"
            KeyEvent.KEYCODE_MEDIA_STOP -> "удержание/стоп"
            KeyEvent.KEYCODE_CAMERA, KeyEvent.KEYCODE_FOCUS -> "кнопка съёмки"
            else -> "неизвестная клавиша"
        }

        fun describe(): String =
            "${human()} · ${keyName()} (${keyCode}) из «$source»"

        fun isPress(): Boolean = action == KeyEvent.ACTION_DOWN
    }

    /**
     * Перехват медиа-клавиш. MediaSession нужен именно для того, чтобы нажатия
     * кольца доставались нам, а не последнему проигрывателю музыки.
     */
    class Catcher(
        private val context: Context,
        private val onPress: (Press) -> Unit
    ) {
        private val main = Handler(Looper.getMainLooper())
        private var session: MediaSession? = null
        private var receiver: BroadcastReceiver? = null
        var active = false
            private set

        fun start() {
            if (active) return
            active = true
            try {
                val s = MediaSession(context, "BlueLinkRing")
                s.setFlags(MediaSession.FLAG_HANDLES_MEDIA_BUTTONS)
                s.setCallback(object : MediaSession.Callback() {
                    override fun onMediaButtonEvent(mediaButtonIntent: Intent): Boolean {
                        handle(mediaButtonIntent, "система")
                        return true
                    }
                })
                s.setPlaybackState(
                    PlaybackState.Builder()
                        .setActions(PlaybackState.ACTION_PLAY_PAUSE or PlaybackState.ACTION_SKIP_TO_NEXT or
                            PlaybackState.ACTION_SKIP_TO_PREVIOUS or PlaybackState.ACTION_STOP or
                            PlaybackState.ACTION_PLAY)
                        .setState(PlaybackState.STATE_PLAYING, 0, 1f)
                        .build()
                )
                s.isActive = true
                session = s
            } catch (e: Exception) {
                active = false
                return
            }
            try {
                val r = object : BroadcastReceiver() {
                    override fun onReceive(c: Context?, intent: Intent?) {
                        if (intent != null) handle(intent, "медиа-кнопка")
                    }
                }
                val filter = IntentFilter(Intent.ACTION_MEDIA_BUTTON)
                filter.priority = Int.MAX_VALUE
                if (Build.VERSION.SDK_INT >= 33) {
                    context.registerReceiver(r, filter, Context.RECEIVER_EXPORTED)
                } else {
                    @Suppress("UnspecifiedRegisterReceiverFlag")
                    context.registerReceiver(r, filter)
                }
                receiver = r
            } catch (e: Exception) {
                // Медиа-сессия уже ловит; приёмник — подстраховка.
            }
        }

        fun stop() {
            active = false
            try {
                session?.isActive = false
                session?.release()
            } catch (ignored: Exception) {
            }
            session = null
            try {
                receiver?.let { context.unregisterReceiver(it) }
            } catch (ignored: Exception) {
            }
            receiver = null
        }

        @Suppress("DEPRECATION")
        private fun handle(intent: Intent, source: String) {
            val event = intent.getParcelableExtra(Intent.EXTRA_KEY_EVENT) as? KeyEvent ?: return
            val press = Press(event.keyCode, event.scanCode, event.action, source)
            main.post { onPress(press) }
        }

        /** Нажатия, пришедшие прямо в окно приложения (стрелки, громкость, кнопка камеры). */
        fun fromKeyEvent(event: KeyEvent): Press =
            Press(event.keyCode, event.scanCode, event.action, "окно приложения")
    }

    /** Что система думает про кольцо как про устройство ввода. */
    data class InputState(val devices: List<String>, val hidHost: Int, val hidHostText: String)

    fun inputState(context: Context): InputState {
        val names = ArrayList<String>()
        try {
            val im = context.getSystemService(Context.INPUT_SERVICE) as android.hardware.input.InputManager
            for (id in im.inputDeviceIds) {
                val dev = im.getInputDevice(id) ?: continue
                if (!dev.isVirtual && dev.name.isNotBlank()) names.add(dev.name)
            }
        } catch (ignored: Exception) {
        }
        val state = try {
            val adapter = BluetoothAdapter.getDefaultAdapter()
            if (adapter == null) -1 else rawHidState(adapter)
        } catch (e: Exception) {
            -1
        }
        val text = when (state) {
            BluetoothProfile.STATE_CONNECTED -> "подключено как пульт"
            BluetoothProfile.STATE_CONNECTING -> "подключается как пульт"
            BluetoothProfile.STATE_DISCONNECTED -> "не подключено как пульт"
            else -> "неизвестно"
        }
        return InputState(names, state, text)
    }

    private fun rawHidState(adapter: BluetoothAdapter): Int {
        return try {
            val m = BluetoothAdapter::class.java.getMethod("getProfileConnectionState", Int::class.javaPrimitiveType)
            (m.invoke(adapter, BluetoothProfile.HID_HOST) as? Int) ?: -1
        } catch (e: Exception) {
            -1
        }
    }

    /** Фонарик телефона: заметное действие без участия очков. */
    class Torch(private val context: Context) {
        private var on = false
        val isOn: Boolean get() = on

        fun toggle(): Boolean {
            val target = !on
            return try {
                val cm = context.getSystemService(Context.CAMERA_SERVICE) as CameraManager
                val id = cm.cameraIdList.firstOrNull { cam ->
                    cm.getCameraCharacteristics(cam)
                        .get(CameraCharacteristics.FLASH_INFO_AVAILABLE) == true &&
                        cm.getCameraCharacteristics(cam)
                            .get(CameraCharacteristics.LENS_FACING) == CameraCharacteristics.LENS_FACING_BACK
                } ?: cm.cameraIdList.firstOrNull()
                if (id == null) {
                    false
                } else {
                    cm.setTorchMode(id, target)
                    on = target
                    true
                }
            } catch (e: Exception) {
                false
            }
        }
    }

    /** Опись того, что о кольце знает сама система — без наших догадок. */
    fun describeInput(state: InputState, ringName: String): String = buildString {
        appendLine("Кольцо как пульт: ${state.hidHostText}")
        if (state.devices.isEmpty()) {
            append("Устройства ввода: система не перечислила ни одного")
        } else {
            val mentions = state.devices.filter {
                val n = it.lowercase()
                n.contains("ring") || n.contains("кольц") ||
                    (ringName.isNotBlank() && n.contains(ringName.lowercase().take(6)))
            }
            appendLine("Устройства ввода в системе: ${state.devices.size}")
            if (mentions.isEmpty()) {
                append("Среди них нет кольца по названию — значит, система держит его только как BLE-устройство")
            } else {
                append("Кольцо видно как устройство ввода: " + mentions.joinToString(", "))
            }
        }
    }
}
