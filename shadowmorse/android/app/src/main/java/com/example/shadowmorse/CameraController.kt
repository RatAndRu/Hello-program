package com.example.shadowmorse

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.graphics.Matrix
import android.graphics.RectF
import android.graphics.SurfaceTexture
import android.hardware.camera2.CameraCaptureSession
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CameraManager
import android.hardware.camera2.CaptureRequest
import android.media.ImageReader
import android.os.Handler
import android.os.HandlerThread
import android.util.Size
import android.view.Surface
import android.view.TextureView
import kotlin.math.abs
import kotlin.math.max

/** Camera2: превью на TextureView + отдельный маленький YUV-поток для распознавания света. */
class CameraController(
    private val context: Context,
    private val textureView: TextureView,
    private val onDetections: (FrameDetections) -> Unit,
    private val onError: (String) -> Unit
) {
    private val detector = LightDetector()
    private var backgroundThread: HandlerThread? = null
    private var backgroundHandler: Handler? = null
    private var cameraDevice: CameraDevice? = null
    private var captureSession: CameraCaptureSession? = null
    private var imageReader: ImageReader? = null
    private var previewSize = Size(1280, 720)
    private var sensorOrientation = 0
    private var frameCounter = 0

    fun start() {
        if (context.checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) return
        startBackgroundThread()
        if (textureView.isAvailable) openCamera(textureView.width, textureView.height)
        else textureView.surfaceTextureListener = object : TextureView.SurfaceTextureListener {
            override fun onSurfaceTextureAvailable(surface: SurfaceTexture, width: Int, height: Int) = openCamera(width, height)
            override fun onSurfaceTextureSizeChanged(surface: SurfaceTexture, width: Int, height: Int) = configureTransform(width, height)
            override fun onSurfaceTextureDestroyed(surface: SurfaceTexture): Boolean { stop(); return true }
            override fun onSurfaceTextureUpdated(surface: SurfaceTexture) = Unit
        }
    }

    fun stop() {
        try { captureSession?.close() } catch (_: Exception) { }
        captureSession = null
        try { cameraDevice?.close() } catch (_: Exception) { }
        cameraDevice = null
        try { imageReader?.close() } catch (_: Exception) { }
        imageReader = null
        backgroundThread?.quitSafely()
        try { backgroundThread?.join(300) } catch (_: InterruptedException) { }
        backgroundThread = null
        backgroundHandler = null
    }

    private fun startBackgroundThread() {
        if (backgroundThread != null) return
        backgroundThread = HandlerThread("ShadowMorseCamera").also { it.start() }
        backgroundHandler = Handler(backgroundThread!!.looper)
    }

    private fun openCamera(viewWidth: Int, viewHeight: Int) {
        try {
            val manager = context.getSystemService(Context.CAMERA_SERVICE) as CameraManager
            val cameraId = manager.cameraIdList.firstOrNull { id ->
                manager.getCameraCharacteristics(id).get(CameraCharacteristics.LENS_FACING) == CameraCharacteristics.LENS_FACING_BACK
            } ?: manager.cameraIdList.firstOrNull() ?: run { onError("Камера не найдена"); return }
            val characteristics = manager.getCameraCharacteristics(cameraId)
            sensorOrientation = characteristics.get(CameraCharacteristics.SENSOR_ORIENTATION) ?: 0
            val map = characteristics.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)
            val previewChoices = map?.getOutputSizes(SurfaceTexture::class.java)?.toList().orEmpty()
            previewSize = chooseSize(previewChoices, 1280, 720)
            val analysisSize = chooseSize(map?.getOutputSizes(android.graphics.ImageFormat.YUV_420_888)?.toList().orEmpty(), 640, 480)

            configureTransform(viewWidth, viewHeight)
            val texture = textureView.surfaceTexture ?: return
            texture.setDefaultBufferSize(previewSize.width, previewSize.height)
            val previewSurface = Surface(texture)
            imageReader = ImageReader.newInstance(analysisSize.width, analysisSize.height, android.graphics.ImageFormat.YUV_420_888, 3).apply {
                setOnImageAvailableListener({ reader ->
                    val image = try { reader.acquireLatestImage() } catch (_: Exception) { null }
                    if (image != null) {
                        try {
                            // Анализируем каждый второй кадр: для вспышек/лазера достаточно, а телефон меньше греется.
                            if (++frameCounter % 2 == 0) onDetections(detector.process(image, sensorOrientation))
                        } catch (_: Exception) { }
                        image.close()
                    }
                }, backgroundHandler)
            }
            val analysisSurface = imageReader!!.surface

            @Suppress("MissingPermission")
            manager.openCamera(cameraId, object : CameraDevice.StateCallback() {
                override fun onOpened(camera: CameraDevice) {
                    cameraDevice = camera
                    try {
                        camera.createCaptureSession(listOf(previewSurface, analysisSurface), object : CameraCaptureSession.StateCallback() {
                            override fun onConfigured(session: CameraCaptureSession) {
                                captureSession = session
                                try {
                                    val request = camera.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW).apply {
                                        addTarget(previewSurface)
                                        addTarget(analysisSurface)
                                        set(CaptureRequest.CONTROL_MODE, CaptureRequest.CONTROL_MODE_AUTO)
                                        set(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_PICTURE)
                                        set(CaptureRequest.CONTROL_AE_MODE, CaptureRequest.CONTROL_AE_MODE_ON)
                                    }
                                    session.setRepeatingRequest(request.build(), null, backgroundHandler)
                                } catch (e: Exception) { onError("Не удалось запустить превью камеры") }
                            }
                            override fun onConfigureFailed(session: CameraCaptureSession) = onError("Не удалось настроить камеру")
                        }, backgroundHandler)
                    } catch (e: Exception) { onError("Не удалось создать сессию камеры") }
                }
                override fun onDisconnected(camera: CameraDevice) { camera.close(); cameraDevice = null }
                override fun onError(camera: CameraDevice, error: Int) { camera.close(); cameraDevice = null; onError("Ошибка камеры: $error") }
            }, backgroundHandler)
        } catch (e: Exception) {
            onError("Не удалось открыть камеру")
        }
    }

    private fun chooseSize(choices: List<Size>, desiredW: Int, desiredH: Int): Size {
        if (choices.isEmpty()) return Size(desiredW, desiredH)
        val bigEnough = choices.filter { it.width >= 320 && it.height >= 240 }
        return (bigEnough.ifEmpty { choices }).minByOrNull { size ->
            abs(size.width * desiredH - size.height * desiredW) + abs(size.width - desiredW) / 4
        } ?: choices.first()
    }

    private fun configureTransform(viewWidth: Int, viewHeight: Int) {
        if (viewWidth <= 0 || viewHeight <= 0) return
        val matrix = Matrix()
        val viewRect = RectF(0f, 0f, viewWidth.toFloat(), viewHeight.toFloat())
        val bufferRect = RectF(0f, 0f, previewSize.height.toFloat(), previewSize.width.toFloat())
        val centerX = viewRect.centerX()
        val centerY = viewRect.centerY()
        // Для портретного телефона задняя камера обычно имеет sensorOrientation=90.
        if (sensorOrientation == 90 || sensorOrientation == 270) {
            bufferRect.offset(centerX - bufferRect.centerX(), centerY - bufferRect.centerY())
            matrix.setRectToRect(viewRect, bufferRect, Matrix.ScaleToFit.FILL)
            val scale = max(viewHeight.toFloat() / previewSize.height.toFloat(), viewWidth.toFloat() / previewSize.width.toFloat())
            matrix.postScale(scale, scale, centerX, centerY)
            matrix.postRotate((90 * (sensorOrientation / 90 - 2)).toFloat(), centerX, centerY)
        }
        textureView.setTransform(matrix)
    }
}
