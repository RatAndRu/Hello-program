package com.example.shadowmorse

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.pm.PackageManager
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.TextureView
import android.view.View
import android.view.WindowManager
import android.widget.Button
import android.widget.CheckBox
import android.widget.TextView
import android.widget.Toast
import kotlin.math.PI
import kotlin.math.abs

class MainActivity : Activity(), SensorEventListener {
    private lateinit var gameView: GameView
    private lateinit var cameraPreview: TextureView
    private lateinit var topHud: View
    private lateinit var startPanel: View
    private lateinit var endPanel: View
    private lateinit var timeText: TextView
    private lateinit var livesText: TextView
    private lateinit var scoreText: TextView
    private lateinit var endTitle: TextView
    private lateinit var endStats: TextView
    private lateinit var toastText: TextView

    private var cameraController: CameraController? = null
    private var sensorManager: SensorManager? = null
    private var rotationSensor: Sensor? = null
    private val rotationMatrix = FloatArray(9)
    private var baseYaw: Float? = null
    private var basePitch: Float? = null
    private var latestYaw = 0f
    private var latestPitch = 0f
    private var hasOrientation = false
    private var gameRunning = false
    private val mainHandler = Handler(Looper.getMainLooper())
    private var toastRunnable: Runnable? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        setContentView(R.layout.activity_main)
        applyImmersive()

        gameView = findViewById(R.id.gameView)
        cameraPreview = findViewById(R.id.cameraPreview)
        topHud = findViewById(R.id.topHud)
        startPanel = findViewById(R.id.startPanel)
        endPanel = findViewById(R.id.endPanel)
        timeText = findViewById(R.id.timeText)
        livesText = findViewById(R.id.livesText)
        scoreText = findViewById(R.id.scoreText)
        endTitle = findViewById(R.id.endTitle)
        endStats = findViewById(R.id.endStats)
        toastText = findViewById(R.id.toastText)

        gameView.listener = object : GameView.Listener {
            override fun onHud(state: GameView.HudState) {
                runOnUiThread {
                    timeText.text = "⏱ ${formatTime(state.timeLeftSec)}"
                    livesText.text = "❤ ${state.lives}"
                    scoreText.text = "☠ ${state.score}"
                }
            }

            override fun onGameEnd(win: Boolean, score: Int, elapsedSec: Int) {
                runOnUiThread {
                    gameRunning = false
                    topHud.visibility = View.GONE
                    endPanel.visibility = View.VISIBLE
                    endTitle.text = if (win) "Ты выжил!" else "Тьма добралась до тебя"
                    endStats.text = "Уничтожено монстров: $score. Время: $elapsedSec сек."
                }
            }

            override fun onToast(text: String) = runOnUiThread { showToast(text) }
        }

        sensorManager = getSystemService(Context.SENSOR_SERVICE) as SensorManager
        rotationSensor = sensorManager?.getDefaultSensor(Sensor.TYPE_ROTATION_VECTOR)
            ?: sensorManager?.getDefaultSensor(Sensor.TYPE_GEOMAGNETIC_ROTATION_VECTOR)

        findViewById<Button>(R.id.startBtn).setOnClickListener {
            if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
                requestPermissions(arrayOf(Manifest.permission.CAMERA), REQ_CAMERA_START)
            } else startGame()
        }
        findViewById<Button>(R.id.calibrateBtn).setOnClickListener {
            calibrateOrientation()
        }
        findViewById<Button>(R.id.restartBtn).setOnClickListener { startGame() }
    }

    override fun onResume() {
        super.onResume()
        applyImmersive()
        rotationSensor?.let { sensor ->
            sensorManager?.registerListener(this, sensor, SensorManager.SENSOR_DELAY_GAME)
        }
        if (checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) startCamera()
        gameView.invalidate()
    }

    override fun onPause() {
        sensorManager?.unregisterListener(this)
        cameraController?.stop()
        cameraController = null
        if (gameRunning) {
            gameRunning = false
            gameView.stopGame()
            topHud.visibility = View.GONE
            startPanel.visibility = View.VISIBLE
        }
        super.onPause()
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED) {
            startCamera()
            if (requestCode == REQ_CAMERA_START) startGame()
        } else {
            showToast("Без камеры игра не сможет видеть фонарь и лазер")
        }
    }

    private fun startCamera() {
        if (cameraController != null) return
        cameraController = CameraController(
            context = this,
            textureView = cameraPreview,
            onDetections = { detections -> gameView.setDetections(detections) },
            onError = { message -> runOnUiThread { showToast(message) } },
            onVideoAspect = { aspect -> gameView.setVideoAspect(aspect) }
        ).also { it.start() }
    }

    private fun startGame() {
        val debug = findViewById<CheckBox>(R.id.debugTouchCheck).isChecked
        startCamera()
        // В режиме без фонарей детектор света не работает вообще: ни урона от света, ни анализа кадров.
        cameraController?.setLightAnalysisEnabled(!debug)
        calibrateOrientation(silent = true)
        startPanel.visibility = View.GONE
        endPanel.visibility = View.GONE
        topHud.visibility = View.VISIBLE
        gameRunning = true
        gameView.debugTouchMode = debug
        gameView.startGame()
        showToast(if (debug) "Отладка: призраки — тапом, пауки — свайпом" else "Поворачивайся вокруг себя. Удачи!")
    }

    private fun calibrateOrientation(silent: Boolean = false) {
        if (hasOrientation) {
            baseYaw = latestYaw
            basePitch = latestPitch
            gameView.setOrientation(0f, 0f, true)
            if (!silent) showToast("Направление откалибровано")
        } else if (!silent) {
            showToast("Датчик поворота не найден: веди палец по экрану")
        }
    }

    override fun onSensorChanged(event: SensorEvent) {
        if (event.sensor.type != Sensor.TYPE_ROTATION_VECTOR && event.sensor.type != Sensor.TYPE_GEOMAGNETIC_ROTATION_VECTOR) return
        SensorManager.getRotationMatrixFromVector(rotationMatrix, event.values)
        // Не используем Euler-углы getOrientation(): в портрете они легко дают перепутанные оси
        // (вертикальный наклон телефона начинал двигать монстров по горизонтали).
        // Берём напрямую оптическую ось камеры: камера смотрит вдоль -Z устройства.
        // Матрица rotation vector переводит координаты устройства в мировые (X=восток, Y=север, Z=вверх),
        // поэтому направление взгляда = минус третий столбец матрицы.
        val forwardX = -rotationMatrix[2]
        val forwardY = -rotationMatrix[5]
        val forwardZ = -rotationMatrix[8]
        // Азимут взгляда: по часовой стрелке от севера. Поворот игрока направо увеличивает азимут,
        // поэтому неподвижный монстр на экране уходит влево — как и должно быть.
        latestYaw = Math.toDegrees(kotlin.math.atan2(forwardX.toDouble(), forwardY.toDouble())).toFloat()
        // Тангаж взгляда: вверх положителен. Поднял телефон — монстр на экране уходит вниз.
        latestPitch = Math.toDegrees(kotlin.math.asin(forwardZ.coerceIn(-1f, 1f).toDouble())).toFloat()
        hasOrientation = true
        val baseY = baseYaw
        val baseP = basePitch
        if (baseY != null && baseP != null) {
            gameView.setOrientation(deltaAngle(latestYaw, baseY), (latestPitch - baseP).coerceIn(-80f, 80f), true)
        } else {
            gameView.setOrientation(0f, 0f, true)
        }
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) = Unit

    private fun deltaAngle(a: Float, b: Float): Float {
        var d = a - b
        while (d > 180f) d -= 360f
        while (d < -180f) d += 360f
        return d
    }

    private fun showToast(text: String) {
        toastRunnable?.let { mainHandler.removeCallbacks(it) }
        toastText.text = text
        toastText.visibility = View.VISIBLE
        toastRunnable = Runnable { toastText.visibility = View.GONE }
        mainHandler.postDelayed(toastRunnable!!, 2400L)
    }

    private fun formatTime(totalSec: Int): String = "%02d:%02d".format(totalSec / 60, totalSec % 60)

    private fun applyImmersive() {
        @Suppress("DEPRECATION")
        window.decorView.systemUiVisibility = (
            View.SYSTEM_UI_FLAG_FULLSCREEN or
                View.SYSTEM_UI_FLAG_HIDE_NAVIGATION or
                View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY or
                View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN or
                View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
            )
    }

    companion object {
        private const val REQ_CAMERA_START = 4101
    }
}
