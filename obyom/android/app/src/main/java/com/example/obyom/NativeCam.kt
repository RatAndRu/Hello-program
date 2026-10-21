package com.example.obyom

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.ImageFormat
import android.graphics.Rect
import android.graphics.YuvImage
import android.hardware.camera2.CameraCaptureSession
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CameraManager
import android.hardware.camera2.CaptureRequest
import android.media.Image
import android.media.ImageReader
import android.os.Handler
import android.os.HandlerThread
import android.util.Base64
import android.util.Size
import java.io.ByteArrayOutputStream

/**
 * Собственная камера приложения (Camera2) вместо камеры WebView.
 *
 * Зачем: в Android WebView есть ошибка Chromium (issues.chromium.org/40884226): на части телефонов
 * изображение getUserMedia «замирает» и идёт, только пока палец касается экрана. Google её не исправил.
 * Здесь кадры берутся напрямую из камеры и по запросу веб-части отдаются ей как JPEG (base64).
 *
 * Кадр сжимается только когда веб-часть забрала предыдущий (wanted) — без лишней работы процессора.
 */
class NativeCam(private val ctx: Context) {
    private var thread: HandlerThread? = null
    private var handler: Handler? = null
    private var device: CameraDevice? = null
    private var session: CameraCaptureSession? = null
    private var reader: ImageReader? = null
    private var nv21: ByteArray? = null
    private val lock = Object()

    @Volatile private var wanted = true
    private var jpeg: String? = null
    private var frameId = 0
    @Volatile var lastError = ""
    @Volatile var running = false
        private set
    var width = 0
        private set
    var height = 0
        private set
    var sensorOrientation = 90
        private set
    var reqW = 1280
        private set
    var reqH = 720
        private set

    @SuppressLint("MissingPermission")
    @Synchronized
    fun start(w: Int, h: Int): String {
        if (running) return "ok"
        reqW = w; reqH = h; lastError = ""
        val mgr = ctx.getSystemService(Context.CAMERA_SERVICE) as CameraManager
        val ids = mgr.cameraIdList
        val id = ids.firstOrNull {
            mgr.getCameraCharacteristics(it).get(CameraCharacteristics.LENS_FACING) == CameraCharacteristics.LENS_FACING_BACK
        } ?: ids.firstOrNull() ?: return "камера не найдена"
        val ch = mgr.getCameraCharacteristics(id)
        val map = ch.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP) ?: return "камера не отдаёт кадры"
        val size = pickSize(map.getOutputSizes(ImageFormat.YUV_420_888) ?: return "камера не отдаёт кадры YUV", w, h)
        sensorOrientation = ch.get(CameraCharacteristics.SENSOR_ORIENTATION) ?: 90
        width = size.width; height = size.height
        val afModes = ch.get(CameraCharacteristics.CONTROL_AF_AVAILABLE_MODES) ?: IntArray(0)
        val af = when {
            afModes.contains(CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_PICTURE) -> CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_PICTURE
            afModes.contains(CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_VIDEO) -> CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_VIDEO
            else -> -1
        }

        val th = HandlerThread("obyom-cam").also { it.start() }
        val hd = Handler(th.looper)
        thread = th; handler = hd
        val rd = ImageReader.newInstance(width, height, ImageFormat.YUV_420_888, 3)
        rd.setOnImageAvailableListener({ r -> onImage(r) }, hd)
        reader = rd
        running = true; wanted = true
        try {
            mgr.openCamera(id, object : CameraDevice.StateCallback() {
                override fun onOpened(d: CameraDevice) {
                    if (!running) { d.close(); return }
                    device = d
                    try { createSession(d, rd, hd, af) } catch (e: Exception) { lastError = "камера: ${e.message}" }
                }
                override fun onDisconnected(d: CameraDevice) { d.close(); if (device === d) device = null; lastError = "камеру заняло другое приложение" }
                override fun onError(d: CameraDevice, error: Int) { d.close(); if (device === d) device = null; lastError = "ошибка камеры ($error)" }
            }, hd)
        } catch (e: Exception) {
            stop(); return "не удалось открыть камеру: ${e.message}"
        }
        return "ok"
    }

    @Suppress("DEPRECATION")
    private fun createSession(d: CameraDevice, rd: ImageReader, hd: Handler, af: Int) {
        val surf = rd.surface
        d.createCaptureSession(listOf(surf), object : CameraCaptureSession.StateCallback() {
            override fun onConfigured(s: CameraCaptureSession) {
                if (!running) { s.close(); return }
                session = s
                try {
                    val rb = d.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW)
                    rb.addTarget(surf)
                    rb.set(CaptureRequest.CONTROL_MODE, CaptureRequest.CONTROL_MODE_AUTO)
                    if (af >= 0) rb.set(CaptureRequest.CONTROL_AF_MODE, af)
                    s.setRepeatingRequest(rb.build(), null, hd)
                } catch (e: Exception) { lastError = "камера: ${e.message}" }
            }
            override fun onConfigureFailed(s: CameraCaptureSession) { lastError = "не удалось настроить камеру" }
        }, hd)
    }

    private fun onImage(r: ImageReader) {
        var acquired: Image? = null
        try { acquired = r.acquireLatestImage() } catch (e: Exception) {}
        val img = acquired ?: return
        try {
            if (!wanted) return
            val w = img.width; val h = img.height
            val data = toNV21(img)
            val out = ByteArrayOutputStream(w * h / 4)
            YuvImage(data, ImageFormat.NV21, w, h, null).compressToJpeg(Rect(0, 0, w, h), 90, out)
            val b64 = Base64.encodeToString(out.toByteArray(), Base64.NO_WRAP)
            synchronized(lock) { jpeg = b64; frameId++ }
            wanted = false
        } catch (e: Exception) {
            lastError = "кадр: ${e.message}"
        } finally {
            img.close()
        }
    }

    /** Новый кадр после [last]: "id|w|h|b64", "" — пока нет нового, "E:текст" — ошибка. */
    fun frame(last: Int): String {
        synchronized(lock) {
            val j = jpeg
            if (j != null && frameId != last) {
                wanted = true
                return "$frameId|$width|$height|$j"
            }
        }
        wanted = true
        val e = lastError
        return if (e.isNotEmpty()) "E:$e" else ""
    }

    @Synchronized
    fun stop() {
        running = false
        val hd = handler; val th = thread
        val s = session; val d = device; val rd = reader
        session = null; device = null; reader = null; handler = null; thread = null
        val close = Runnable {
            try { s?.close() } catch (e: Exception) {}
            try { d?.close() } catch (e: Exception) {}
            try { rd?.close() } catch (e: Exception) {}
            th?.quitSafely()
        }
        if (hd != null) hd.post(close) else close.run()
        synchronized(lock) { jpeg = null }
    }

    /** YUV_420_888 → NV21 (Y, затем чередующиеся V U) с учётом шагов строк и пикселей. */
    private fun toNV21(img: Image): ByteArray {
        val w = img.width; val h = img.height; val ySize = w * h
        val out = nv21?.takeIf { it.size == ySize * 3 / 2 } ?: ByteArray(ySize * 3 / 2).also { nv21 = it }
        val yP = img.planes[0]; val uP = img.planes[1]; val vP = img.planes[2]
        val yB = yP.buffer; val yRS = yP.rowStride
        if (yP.pixelStride == 1 && yRS == w) {
            yB.position(0); yB.get(out, 0, ySize)
        } else {
            for (y in 0 until h) { yB.position(y * yRS); yB.get(out, y * w, w) }
        }
        val uB = uP.buffer; val vB = vP.buffer
        val uRS = uP.rowStride; val uPS = uP.pixelStride; val vRS = vP.rowStride; val vPS = vP.pixelStride
        var o = ySize
        for (y in 0 until h / 2) {
            val ur = y * uRS; val vr = y * vRS
            for (x in 0 until w / 2) {
                out[o++] = vB.get(vr + x * vPS)
                out[o++] = uB.get(ur + x * uPS)
            }
        }
        return out
    }

    /** Размер 16:9 ближе всего к желаемому (обычно ровно 1280×720), но не больше 1920 по ширине. */
    private fun pickSize(sizes: Array<Size>, w: Int, h: Int): Size {
        val want = w.toDouble() / h
        return sizes.minByOrNull { s ->
            val aspect = Math.abs(s.width.toDouble() / s.height - want)
            val area = Math.abs(Math.log((s.width.toDouble() * s.height) / (w.toDouble() * h)))
            aspect * 10 + area + (if (s.width > 1920) 100.0 else 0.0)
        } ?: sizes[0]
    }
}
