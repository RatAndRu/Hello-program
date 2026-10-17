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
import android.widget.SeekBar
import android.widget.TextView
import android.widget.Toast
import kotlin.math.PI
import kotlin.math.abs

class MainActivity : Activity(), SensorEventListener {
    private lateinit var gameView: GameView
    private lateinit var monster3DView: Monster3DView
    private lateinit var cameraPreview: TextureView
    private lateinit var topHud: View
    private lateinit var startPanel: View
    private lateinit var endPanel: View
    private lateinit var timeText: TextView
    private lateinit var livesText: TextView
    private lateinit var scoreText: TextView
    private lateinit var shardsText: TextView
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
        monster3DView = findViewById(R.id.monster3DView)
        gameView.modelView = monster3DView
        cameraPreview = findViewById(R.id.cameraPreview)
        topHud = findViewById(R.id.topHud)
        startPanel = findViewById(R.id.startPanel)
        endPanel = findViewById(R.id.endPanel)
        timeText = findViewById(R.id.timeText)
        livesText = findViewById(R.id.livesText)
        scoreText = findViewById(R.id.scoreText)
        shardsText = findViewById(R.id.shardsText)
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
                    gameView.stopGame()
                    topHud.visibility = View.GONE
                    findViewById<View>(R.id.exitGameBtn).visibility = View.GONE
                    findViewById<View>(R.id.consumablesPanel).visibility = View.GONE
                    endPanel.visibility = View.VISIBLE
                    endTitle.text = if (win) "Ты выжил!" else "Тьма добралась до тебя"
                    endStats.text = "Уничтожено монстров: $score. Время: $elapsedSec сек."
                }
            }

            override fun onToast(text: String) = runOnUiThread { showToast(text) }

            override fun onInventory(state: GameView.InventoryState) {
                runOnUiThread { renderInventory(state) }
            }

            override fun onUpgradeChoices(choices: List<String>) {
                runOnUiThread { showUpgradeDialog(choices) }
            }
        }

        sensorManager = getSystemService(Context.SENSOR_SERVICE) as SensorManager
        rotationSensor = sensorManager?.getDefaultSensor(Sensor.TYPE_ROTATION_VECTOR)
            ?: sensorManager?.getDefaultSensor(Sensor.TYPE_GEOMAGNETIC_ROTATION_VECTOR)

        setupSettings()
        buildConsumablesBar()
        findViewById<Button>(R.id.startBtn).setOnClickListener {
            if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
                requestPermissions(arrayOf(Manifest.permission.CAMERA), REQ_CAMERA_START)
            } else startGame()
        }
        findViewById<Button>(R.id.calibrateBtn).setOnClickListener {
            calibrateOrientation()
        }
        findViewById<Button>(R.id.restartBtn).setOnClickListener { startGame() }
        findViewById<Button>(R.id.exitGameBtn).setOnClickListener { exitToMainMenu() }
        findViewById<Button>(R.id.endMenuBtn).setOnClickListener { exitToMainMenu() }
    }

    override fun onResume() {
        super.onResume()
        applyImmersive()
        rotationSensor?.let { sensor ->
            sensorManager?.registerListener(this, sensor, SensorManager.SENSOR_DELAY_GAME)
        }
        if (checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) startCamera()
        if (gameView.use3DModels) monster3DView.onResume()
        gameView.invalidate()
    }

    override fun onPause() {
        monster3DView.onPause()
        sensorManager?.unregisterListener(this)
        cameraController?.stop()
        cameraController = null
        if (gameRunning) showMainMenu()
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
        val prefs = getSharedPreferences("settings", Context.MODE_PRIVATE)
        cameraController?.setSensitivity(
            0.35f + prefs.getInt("flashSensitivity", 50) / 100f * 1.65f,
            0.35f + prefs.getInt("laserSensitivity", 50) / 100f * 1.65f
        )
        gameView.setOrientationSmoothing(0.45f + prefs.getInt("smoothingSensitivity", 50) / 100f * 1.55f)
        calibrateOrientation(silent = true)
        startPanel.visibility = View.GONE
        endPanel.visibility = View.GONE
        topHud.visibility = View.VISIBLE
        findViewById<View>(R.id.exitGameBtn).visibility = View.VISIBLE
        findViewById<View>(R.id.consumablesPanel).visibility = View.VISIBLE
        gameRunning = true
        gameView.debugTouchMode = debug
        val use3D = findViewById<CheckBox>(R.id.models3DCheck).isChecked
        gameView.use3DModels = use3D
        monster3DView.setModelsEnabled(use3D)
        gameView.startGame()
        showToast(if (debug) "Отладка: призраки — тапом, пауки — свайпом" else "Поворачивайся вокруг себя. Удачи!")
    }

    /** Выход в главное меню: матч прекращается и не сохраняется. */
    private fun exitToMainMenu() {
        if (!gameRunning && startPanel.visibility == View.VISIBLE) return
        showMainMenu()
        showToast("Игра остановлена — матч не сохранён")
    }

    private fun showMainMenu() {
        gameRunning = false
        gameView.stopGame()
        topHud.visibility = View.GONE
        findViewById<View>(R.id.exitGameBtn).visibility = View.GONE
        findViewById<View>(R.id.consumablesPanel).visibility = View.GONE
        endPanel.visibility = View.GONE
        startPanel.visibility = View.VISIBLE
    }

    private fun setupSettings() {
        val prefs = getSharedPreferences("settings", Context.MODE_PRIVATE)
        val flash = findViewById<SeekBar>(R.id.flashSensitivity)
        val laser = findViewById<SeekBar>(R.id.laserSensitivity)
        val smoothing = findViewById<SeekBar>(R.id.smoothingSensitivity)
        flash.progress = prefs.getInt("flashSensitivity", 50)
        laser.progress = prefs.getInt("laserSensitivity", 50)
        smoothing.progress = prefs.getInt("smoothingSensitivity", 50)
        findViewById<CheckBox>(R.id.models3DCheck).isChecked = prefs.getBoolean("models3D", true)
        findViewById<CheckBox>(R.id.debugTouchCheck).isChecked = prefs.getBoolean("touchMode", false)
        fun apply() {
            prefs.edit()
                .putInt("flashSensitivity", flash.progress)
                .putInt("laserSensitivity", laser.progress)
                .putInt("smoothingSensitivity", smoothing.progress)
                .putBoolean("models3D", findViewById<CheckBox>(R.id.models3DCheck).isChecked)
                .putBoolean("touchMode", findViewById<CheckBox>(R.id.debugTouchCheck).isChecked)
                .apply()
            val flashLevel = 0.35f + flash.progress / 100f * 1.65f
            val laserLevel = 0.35f + laser.progress / 100f * 1.65f
            cameraController?.setSensitivity(flashLevel, laserLevel)
            gameView.setOrientationSmoothing(0.45f + smoothing.progress / 100f * 1.55f)
        }
        val listener = object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(seekBar: SeekBar?, progress: Int, fromUser: Boolean) { if (fromUser) apply() }
            override fun onStartTrackingTouch(seekBar: SeekBar?) = Unit
            override fun onStopTrackingTouch(seekBar: SeekBar?) = Unit
        }
        flash.setOnSeekBarChangeListener(listener); laser.setOnSeekBarChangeListener(listener); smoothing.setOnSeekBarChangeListener(listener)
        findViewById<CheckBox>(R.id.models3DCheck).setOnCheckedChangeListener { _, _ -> apply() }
        findViewById<CheckBox>(R.id.debugTouchCheck).setOnCheckedChangeListener { _, _ -> apply() }
        // Применить после создания cameraController в onResume: значения продублируются при старте игры.
        mainHandler.postDelayed({ apply() }, 350L)
    }

    private fun buildConsumablesBar() {
        val bar = findViewById<android.widget.LinearLayout>(R.id.consumablesBar)
        bar.removeAllViews()
        GameView.Consumable.values().forEach { type ->
            val button = Button(this).apply {
                textSize = 12f
                setPadding(8, 8, 8, 8)
                setLineSpacing(0f, 0.92f)
                setTextColor(0xFFEEF4FF.toInt())
                setBackgroundResource(R.drawable.consumable_bg)
                layoutParams = android.widget.LinearLayout.LayoutParams((76 * resources.displayMetrics.density).toInt(), (78 * resources.displayMetrics.density).toInt()).apply {
                    marginEnd = (7 * resources.displayMetrics.density).toInt()
                }
                setOnClickListener { gameView.useConsumable(type) }
            }
            button.tag = type
            bar.addView(button)
        }
    }

    private fun renderInventory(state: GameView.InventoryState) {
        // Осколки живут в единственном месте — верхнем HUD. Здесь не повторяем жизни и счёт.
        shardsText.text = "◆ ${state.shards}"
        findViewById<TextView>(R.id.shieldStateText).visibility = if (state.shieldActive) View.VISIBLE else View.GONE
        val bar = findViewById<android.widget.LinearLayout>(R.id.consumablesBar)
        for (i in 0 until bar.childCount) {
            val button = bar.getChildAt(i) as Button
            val type = button.tag as GameView.Consumable
            val count = state.counts[type] ?: 0
            // Три короткие строки: иконка, название, количество. Без повторного текста здоровья/счёта.
            button.text = "${type.icon}\n${type.title}\n×$count"
            button.isEnabled = count > 0
            button.alpha = if (count > 0) 1f else 0.52f
            button.setBackgroundResource(if (count > 0) R.drawable.consumable_bg else R.drawable.consumable_empty_bg)
        }
    }

    private fun showUpgradeDialog(choices: List<String>) {
        if (isFinishing || isDestroyed) { gameView.cancelUpgradeChoice(); return }
        android.app.AlertDialog.Builder(this)
            .setTitle("Усиление за осколки тьмы")
            .setItems(choices.toTypedArray()) { _, which -> gameView.applyUpgradeChoice(which) }
            .setOnCancelListener { gameView.cancelUpgradeChoice() }
            .show()
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
