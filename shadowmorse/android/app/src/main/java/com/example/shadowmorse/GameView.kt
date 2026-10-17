package com.example.shadowmorse

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RadialGradient
import android.graphics.Shader
import android.util.AttributeSet
import android.view.MotionEvent
import android.view.View
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.hypot
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sin
import kotlin.random.Random

/** Игровой оверлей поверх камеры: монстры, эффекты света/лазера, радар, прицел и частицы. */
class GameView @JvmOverloads constructor(context: Context, attrs: AttributeSet? = null) : View(context, attrs) {
    enum class MonsterType { FLASH, LASER }

    data class HudState(val timeLeftSec: Int, val lives: Int, val score: Int)

    var listener: Listener? = null

    interface Listener {
        fun onHud(state: HudState)
        fun onGameEnd(win: Boolean, score: Int, elapsedSec: Int)
        fun onToast(text: String)
    }

    private data class Monster(
        val id: Int,
        val type: MonsterType,
        var hp: Int,
        val maxHp: Int,
        var yaw: Float,
        var pitch: Float,
        var dist: Float,
        var speed: Float,
        val phase: Float,
        val wobble: Float,
        var lastHitAt: Float = -99f,
        var hitFlash: Float = 0f,
        var age: Float = 0f,
        var lastLaserTrack: Long = 0L,
        var laserInsideUntil: Float = -1f
    )

    private data class Particle(
        var x: Float, var y: Float, var vx: Float, var vy: Float,
        var life: Float, val maxLife: Float, val color: Int, val size: Float
    )

    companion object {
        const val DURATION_SEC = 300f
        const val START_LIVES = 3
        const val H_FOV = 160f
        const val V_FOV = 90f
    }

    private val monsters = mutableListOf<Monster>()
    private val particles = mutableListOf<Particle>()
    private var running = false
    private var elapsed = 0f
    private var lives = START_LIVES
    private var score = 0
    private var nextSpawn = 0.5f
    private var nextMonsterId = 1
    private var lastFrameMs = 0L
    private var hudTick = 0f
    private var hurtFlash = 0f

    @Volatile private var detections = FrameDetections()
    private var previousFlashActive = false
    private var flashLastOffMs = 0L
    private var flashRising = false

    private var smoothYaw = 0f
    private var smoothPitch = 0f
    private var targetYaw = 0f
    private var targetPitch = 0f
    private var manualYaw = 0f
    private var manualPitch = 0f
    private var hasSensorOrientation = false
    /** Отладочный режим без внешнего света: тап = вспышка по призраку, свайп = лазер по пауку. */
    var debugTouchMode: Boolean = false
    private var videoAspect: Float = 9f / 16f // ширина/высота уже повёрнутого вертикального кадра
    private val debugTrail = mutableListOf<Pair<Float, Float>>()
    private val debugSwipeHitIds = mutableSetOf<Int>()
    private var debugDownAt = 0L
    private var debugDownX = 0f
    private var debugDownY = 0f
    private var debugMoved = false
    private var dragging = false
    private var dragX = 0f
    private var dragY = 0f

    private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val textPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.argb(210, 255, 255, 255)
        textAlign = Paint.Align.CENTER
        typeface = android.graphics.Typeface.DEFAULT_BOLD
    }

    fun startGame() {
        running = true
        elapsed = 0f
        lives = START_LIVES
        score = 0
        monsters.clear()
        particles.clear()
        nextSpawn = 0.45f
        nextMonsterId = 1
        hurtFlash = 0f
        previousFlashActive = false
        lastFrameMs = 0L
        pushHud()
        invalidate()
    }

    fun stopGame() {
        running = false
        invalidate()
    }

    fun setDetections(value: FrameDetections) {
        detections = value
    }

    fun setVideoAspect(aspectWidthOverHeight: Float) {
        if (aspectWidthOverHeight > 0f) videoAspect = aspectWidthOverHeight
    }

    /** Относительные углы от калиброванной точки, градусы. */
    fun setOrientation(yawDeg: Float, pitchDeg: Float, fromSensor: Boolean) {
        targetYaw = yawDeg
        targetPitch = pitchDeg.coerceIn(-80f, 80f)
        hasSensorOrientation = fromSensor
    }

    override fun onTouchEvent(event: MotionEvent): Boolean {
        if (debugTouchMode && running) {
            handleDebugTouch(event)
            return true
        }
        if (hasSensorOrientation && running) return true
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> { dragging = true; dragX = event.x; dragY = event.y; parent?.requestDisallowInterceptTouchEvent(true) }
            MotionEvent.ACTION_MOVE -> if (dragging) {
                manualYaw += (event.x - dragX) * 0.18f
                manualPitch = (manualPitch - (event.y - dragY) * 0.12f).coerceIn(-45f, 45f)
                if (!hasSensorOrientation) { targetYaw = manualYaw; targetPitch = manualPitch }
                dragX = event.x; dragY = event.y
            }
            MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> dragging = false
        }
        return true
    }

    private fun handleDebugTouch(event: MotionEvent) {
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                debugDownAt = System.currentTimeMillis()
                debugDownX = event.x; debugDownY = event.y
                debugMoved = false
                debugTrail.clear()
                debugSwipeHitIds.clear()
                debugTrail += event.x to event.y
                parent?.requestDisallowInterceptTouchEvent(true)
            }
            MotionEvent.ACTION_MOVE -> {
                if (hypot((event.x - debugDownX).toDouble(), (event.y - debugDownY).toDouble()) > 14f * density()) debugMoved = true
                val prev = debugTrail.lastOrNull()
                debugTrail += event.x to event.y
                if (debugTrail.size > 80) debugTrail.removeAt(0)
                if (prev != null) debugSwipeDamage(prev.first, prev.second, event.x, event.y)
            }
            MotionEvent.ACTION_UP -> {
                val quick = System.currentTimeMillis() - debugDownAt < 350L
                if (quick && !debugMoved) debugTapDamage(event.x, event.y)
                else if (debugTrail.size >= 2) {
                    for (i in 1 until debugTrail.size) {
                        val a = debugTrail[i - 1]; val b = debugTrail[i]
                        debugSwipeDamage(a.first, a.second, b.first, b.second)
                    }
                }
                debugTrail.clear()
            }
            MotionEvent.ACTION_CANCEL -> debugTrail.clear()
        }
        invalidate()
    }

    /** Тап в отладке имитирует вспышку: бьёт ближайшего видимого призрака рядом с точкой. */
    private fun debugTapDamage(x: Float, y: Float) {
        var best: Monster? = null
        var bestScreen: ScreenPos? = null
        var bestDist = Float.MAX_VALUE
        for (m in monsters) {
            if (m.type != MonsterType.FLASH) continue
            val s = monsterScreen(m) ?: continue
            val radius = 62f * s.scale * density()
            val d = hypot((s.x - x).toDouble(), (s.y - y).toDouble()).toFloat()
            if (d < radius + 74f * density() && d < bestDist) { best = m; bestScreen = s; bestDist = d }
        }
        val m = best ?: return
        val s = bestScreen ?: return
        if (elapsed - m.lastHitAt > 0.18f) {
            val radius = 62f * s.scale * density()
            hitMonster(m, s.x, s.y, radius)
            if (m.hp <= 0) monsters.remove(m)
        }
    }

    /** Свайп в отладке имитирует лазерную линию: каждый паук получает не более одного разреза за свайп. */
    private fun debugSwipeDamage(x1: Float, y1: Float, x2: Float, y2: Float) {
        if (hypot((x2 - x1).toDouble(), (y2 - y1).toDouble()) < 8f * density()) return
        val iterator = monsters.iterator()
        while (iterator.hasNext()) {
            val m = iterator.next()
            if (m.type != MonsterType.LASER || m.id in debugSwipeHitIds) continue
            val s = monsterScreen(m) ?: continue
            val radius = 52f * s.scale * density()
            val d = distancePointSegment(s.x, s.y, x1, y1, x2, y2)
            if (d < radius * 0.82f) {
                debugSwipeHitIds += m.id
                hitMonster(m, s.x, s.y, radius)
                if (m.hp <= 0) iterator.remove()
            }
        }
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val now = System.currentTimeMillis()
        val dt = if (lastFrameMs == 0L) 0.016f else min(0.05f, (now - lastFrameMs) / 1000f)
        lastFrameMs = now
        if (running) update(dt)
        drawScene(canvas)
        if (running) postInvalidateOnAnimation()
    }

    private fun update(dt: Float) {
        elapsed += dt
        hurtFlash = max(0f, hurtFlash - dt * 1.8f)
        updateOrientation(dt)
        updateFlashEdge()
        updateSpawning(dt)
        updateMonsters(dt)
        updateParticles(dt)
        hudTick -= dt
        if (hudTick <= 0f) { hudTick = 0.12f; pushHud() }
        if (elapsed >= DURATION_SEC) endGame(true)
    }

    private fun updateOrientation(dt: Float) {
        val k = 1f - Math.pow(0.001, dt.toDouble()).toFloat()
        smoothYaw += deltaAngle(targetYaw, smoothYaw) * k
        smoothPitch += (targetPitch - smoothPitch) * k
    }

    private fun updateFlashEdge() {
        val d = detections
        flashRising = false
        if (d.flashActive && !previousFlashActive) {
            val now = System.currentTimeMillis()
            // Нужна именно отдельная вспышка: постоянный свет после короткой паузы не превращается в пулемёт.
            if (now - flashLastOffMs >= 110L || flashLastOffMs == 0L) flashRising = true
        }
        if (!d.flashActive && previousFlashActive) flashLastOffMs = System.currentTimeMillis()
        previousFlashActive = d.flashActive
    }

    private fun updateSpawning(dt: Float) {
        nextSpawn -= dt
        val progress = (elapsed / DURATION_SEC).coerceIn(0f, 1f)
        val interval = lerp(3.4f, 1.55f, progress)
        val maxMonsters = if (progress < 0.5f) 7 else 9
        if (nextSpawn <= 0f && monsters.size < maxMonsters) {
            spawnMonster(progress)
            nextSpawn = interval * Random.nextFloat().let { 0.75f + it * 0.5f }
        }
    }

    private fun spawnMonster(progress: Float) {
        val type = if (Random.nextFloat() < 0.56f) MonsterType.FLASH else MonsterType.LASER
        val hp = when (type) {
            MonsterType.FLASH -> listOf(2, 3, 3, 4).random() + if (progress > 0.72f && Random.nextFloat() < 0.25f) 1 else 0
            MonsterType.LASER -> listOf(2, 2, 3).random()
        }
        var yaw = smoothYaw
        var pitch = smoothPitch
        repeat(12) {
            val side = if (Random.nextFloat() < 0.62f) (if (Random.nextBoolean()) -1f else 1f) * Random.nextFloat().let { 38f + it * 47f } else Random.nextFloat().let { -80f + it * 160f }
            yaw = smoothYaw + side
            pitch = (smoothPitch + Random.nextFloat().let { -36f + it * 72f }).coerceIn(-52f, 52f)
            val separated = monsters.all { other -> hypot(deltaAngle(yaw, other.yaw).toDouble(), (pitch - other.pitch).toDouble()) > 13.0 }
            if (separated) return@repeat
        }
        val baseSpeed = if (type == MonsterType.FLASH) Random.nextFloat().let { 0.030f + it * 0.020f } else Random.nextFloat().let { 0.040f + it * 0.025f }
        monsters += Monster(
            id = nextMonsterId++, type = type, hp = hp, maxHp = hp,
            yaw = yaw, pitch = pitch,
            dist = Random.nextFloat().let { 0.84f + it * 0.16f },
            speed = baseSpeed * (1f + progress * 0.48f),
            phase = Random.nextFloat().let { it * (PI * 2).toFloat() },
            wobble = Random.nextFloat().let { 0.6f + it * 0.8f }
        )
    }

    private fun updateMonsters(dt: Float) {
        val det = detections
        val flashPoint = if (det.flashActive) screenPoint(det.flashU, det.flashV) else null
        val laserPrevU = det.laserPrevU
        val laserPrevV = det.laserPrevV
        val laserSegment = if (det.laserActive && laserPrevU != null && laserPrevV != null) {
            screenPoint(laserPrevU, laserPrevV) to screenPoint(det.laserU, det.laserV)
        } else null

        val iterator = monsters.iterator()
        while (iterator.hasNext()) {
            val m = iterator.next()
            m.age += dt
            m.hitFlash = max(0f, m.hitFlash - dt)
            m.dist -= m.speed * dt
            m.yaw += sin(elapsed * 0.55f + m.phase) * dt * 1.25f
            m.pitch = (m.pitch + cos(elapsed * 0.45f + m.phase) * dt * 0.5f).coerceIn(-55f, 55f)

            val s = monsterScreen(m)
            if (s != null) {
                val radius = (if (m.type == MonsterType.FLASH) 62f else 52f) * s.scale * density()
                if (m.type == MonsterType.FLASH && flashRising && flashPoint != null && elapsed - m.lastHitAt > 0.32f) {
                    val d = hypot((s.x - flashPoint.first).toDouble(), (s.y - flashPoint.second).toDouble())
                    val lightRadius = detections.flashRadius * min(width, height)
                    if (d < radius + lightRadius * 0.68f) hitMonster(m, s.x, s.y, radius)
                }
                if (m.type == MonsterType.LASER && laserSegment != null && elapsed - m.lastHitAt > 0.38f) {
                    val (a, b) = laserSegment
                    val len = hypot((b.first - a.first).toDouble(), (b.second - a.second).toDouble())
                    if (len > 18f * density()) {
                        val d = distancePointSegment(s.x, s.y, a.first, a.second, b.first, b.second)
                        val inside = d < radius * 0.82f
                        // Одно непрерывное ведение лазера = один разрез по конкретному пауку.
                        // Повторный урон возможен новым треком или после выхода точки из паука.
                        if (inside && m.lastLaserTrack != detections.laserTrackId) {
                            m.lastLaserTrack = detections.laserTrackId
                            hitMonster(m, s.x, s.y, radius)
                        }
                        if (!inside && elapsed > m.laserInsideUntil) m.lastLaserTrack = m.lastLaserTrack // трек сохраняется до нового ведения
                    }
                }
            }

            if (m.hp <= 0) {
                iterator.remove()
                continue
            }
            if (m.dist <= 0.02f) {
                iterator.remove()
                lives--
                hurtFlash = 1f
                listener?.onToast("Монстр добрался! -1 жизнь")
                pushHud()
                if (lives <= 0) { endGame(false); return }
            }
        }
    }

    private fun hitMonster(m: Monster, x: Float, y: Float, radius: Float) {
        m.hp -= 1
        m.lastHitAt = elapsed
        m.hitFlash = 0.20f
        spawnParticles(x, y, radius, if (m.type == MonsterType.FLASH) Color.rgb(255, 226, 120) else Color.rgb(255, 76, 90), 12)
        if (m.hp <= 0) {
            score++
            spawnParticles(x, y, radius, if (m.type == MonsterType.FLASH) Color.rgb(150, 190, 255) else Color.rgb(255, 90, 100), 28)
            listener?.onToast(if (m.type == MonsterType.FLASH) "Тень рассеяна вспышкой!" else "Паук рассечён лазером!")
            pushHud()
        }
    }

    private fun endGame(win: Boolean) {
        if (!running) return
        running = false
        pushHud()
        listener?.onGameEnd(win, score, elapsed.toInt())
    }

    private fun pushHud() {
        listener?.onHud(HudState(max(0, (DURATION_SEC - elapsed).toInt()), lives, score))
    }

    private fun updateParticles(dt: Float) {
        val it = particles.iterator()
        while (it.hasNext()) {
            val p = it.next()
            p.life -= dt
            if (p.life <= 0f) it.remove() else {
                p.x += p.vx * dt; p.y += p.vy * dt; p.vy += 260f * dt * density(); p.vx *= 0.985f; p.vy *= 0.99f
            }
        }
    }

    private fun spawnParticles(x: Float, y: Float, radius: Float, color: Int, count: Int) {
        repeat(count) {
            val a = Random.nextFloat() * (PI * 2).toFloat()
            val speed = (40f + Random.nextFloat() * 190f) * density()
            val life = 0.35f + Random.nextFloat() * 0.55f
            particles += Particle(x, y, cos(a) * speed, sin(a) * speed, life, life, color, (2f + Random.nextFloat() * 4f) * density())
        }
        if (particles.size > 420) repeat(particles.size - 420) { particles.removeAt(0) }
    }

    private fun drawScene(canvas: Canvas) {
        drawDarkOverlay(canvas)
        val sorted = monsters.sortedByDescending { it.dist }
        for (m in sorted) drawMonster(canvas, m)
        drawParticles(canvas)
        drawDetections(canvas)
        drawDebugTrail(canvas)
        drawReticle(canvas)
        drawRadar(canvas)
        if (hurtFlash > 0f) {
            paint.shader = null
            paint.style = Paint.Style.FILL
            paint.color = Color.argb((hurtFlash * 90).toInt(), 255, 30, 45)
            canvas.drawRect(0f, 0f, width.toFloat(), height.toFloat(), paint)
        }
    }

    private fun drawDarkOverlay(canvas: Canvas) {
        paint.shader = null
        paint.style = Paint.Style.FILL
        paint.color = Color.argb(72, 0, 0, 16)
        canvas.drawRect(0f, 0f, width.toFloat(), height.toFloat(), paint)
        val radius = max(width, height) * 0.72f
        paint.shader = RadialGradient(width / 2f, height / 2f, radius, intArrayOf(Color.TRANSPARENT, Color.argb(42, 0, 0, 28), Color.argb(190, 0, 0, 0)), floatArrayOf(0f, 0.56f, 1f), Shader.TileMode.CLAMP)
        canvas.drawRect(0f, 0f, width.toFloat(), height.toFloat(), paint)
        paint.shader = null
    }

    private fun drawDetections(canvas: Canvas) {
        val d = detections
        if (d.flashActive) {
            val (x, y) = screenPoint(d.flashU, d.flashV)
            val r = d.flashRadius * min(width, height) * 1.55f
            paint.style = Paint.Style.FILL
            paint.shader = RadialGradient(x, y, r, intArrayOf(Color.argb(92, 255, 246, 180), Color.argb(42, 255, 220, 110), Color.TRANSPARENT), floatArrayOf(0f, 0.45f, 1f), Shader.TileMode.CLAMP)
            canvas.drawCircle(x, y, r, paint)
            paint.shader = null
            paint.style = Paint.Style.STROKE
            paint.strokeWidth = 2f * density()
            paint.color = if (flashRising) Color.argb(245, 255, 255, 220) else Color.argb(150, 255, 230, 120)
            canvas.drawCircle(x, y, r * 0.62f, paint)
        }
        if (d.laserActive) {
            val (x, y) = screenPoint(d.laserU, d.laserV)
            val color = if (d.laserGreen) Color.rgb(76, 255, 106) else Color.rgb(255, 48, 62)
            paint.style = Paint.Style.STROKE
            paint.strokeCap = Paint.Cap.ROUND
            if (d.laserPrevU != null && d.laserPrevV != null) {
                val (px, py) = screenPoint(d.laserPrevU, d.laserPrevV)
                paint.color = Color.argb(70, Color.red(color), Color.green(color), Color.blue(color))
                paint.strokeWidth = 9f * density()
                canvas.drawLine(px, py, x, y, paint)
                paint.color = color
                paint.strokeWidth = 2.4f * density()
                canvas.drawLine(px, py, x, y, paint)
            }
            paint.style = Paint.Style.FILL
            paint.color = color
            canvas.drawCircle(x, y, 5.5f * density(), paint)
            paint.color = Color.WHITE
            canvas.drawCircle(x, y, 1.8f * density(), paint)
        }
    }

    private fun drawDebugTrail(canvas: Canvas) {
        if (!debugTouchMode || debugTrail.size < 2) return
        paint.style = Paint.Style.STROKE
        paint.strokeCap = Paint.Cap.ROUND
        paint.strokeJoin = Paint.Join.ROUND
        paint.color = Color.argb(190, 150, 235, 255)
        paint.strokeWidth = 3f * density()
        val path = Path()
        path.moveTo(debugTrail.first().first, debugTrail.first().second)
        for (i in 1 until debugTrail.size) path.lineTo(debugTrail[i].first, debugTrail[i].second)
        canvas.drawPath(path, paint)
    }

    private fun drawMonster(canvas: Canvas, m: Monster) {
        val s = monsterScreen(m) ?: return
        val base = (if (m.type == MonsterType.FLASH) 76f else 66f) * s.scale * density()
        canvas.save()
        canvas.translate(s.x, s.y)
        val alpha = (s.alpha * 255).toInt().coerceIn(0, 255)
        if (m.hitFlash > 0f) {
            paint.setShadowLayer(30f * density(), 0f, 0f, Color.argb(alpha, 255, 255, 255))
        }
        if (m.type == MonsterType.FLASH) drawWraith(canvas, base, m, alpha) else drawSpider(canvas, base, m, alpha)
        paint.clearShadowLayer()
        drawHp(canvas, -base * 1.08f, base, m, alpha)
        canvas.restore()
    }

    private fun drawWraith(canvas: Canvas, r: Float, m: Monster, alpha: Int) {
        val t = elapsed * 4f + m.phase
        paint.style = Paint.Style.FILL
        paint.shader = RadialGradient(0f, -r * 0.15f, r * 1.08f, intArrayOf(Color.argb(alpha, 105, 120, 165), Color.argb(alpha, 27, 30, 48), Color.argb(0, 0, 0, 0)), floatArrayOf(0f, 0.55f, 1f), Shader.TileMode.CLAMP)
        val path = Path()
        path.moveTo(0f, -r * 0.98f)
        path.cubicTo(-r * 0.78f, -r * 0.74f, -r * 0.80f, -r * 0.02f, -r * 0.48f, r * 0.36f)
        for (i in 0 until 5) {
            val px = -r * 0.48f + i * r * 0.24f
            val py = r * 0.36f + sin(t + i * 1.3f) * r * 0.11f
            path.quadTo(px + r * 0.09f, py + r * 0.24f, px + r * 0.20f, py)
        }
        path.cubicTo(r * 0.80f, -r * 0.02f, r * 0.78f, -r * 0.74f, 0f, -r * 0.98f)
        path.close()
        canvas.drawPath(path, paint)
        paint.shader = null

        // Рваные боковые пряди.
        paint.style = Paint.Style.STROKE
        paint.strokeCap = Paint.Cap.ROUND
        paint.color = Color.argb((alpha * 0.45f).toInt(), 100, 115, 170)
        paint.strokeWidth = r * 0.055f
        for (side in listOf(-1f, 1f)) for (i in 0..2) {
            val startY = -r * 0.18f + i * r * 0.18f
            val wave = sin(t * 1.4f + i) * r * 0.08f
            canvas.drawLine(side * r * 0.48f, startY, side * (r * 0.76f + wave), startY + r * 0.20f, paint)
        }

        // Глаза и рот.
        paint.style = Paint.Style.FILL
        paint.color = Color.argb(alpha, 255, 244, 178)
        canvas.drawOval(-r * 0.31f, -r * 0.34f, -r * 0.12f, -r * 0.22f, paint)
        canvas.drawOval(r * 0.12f, -r * 0.34f, r * 0.31f, -r * 0.22f, paint)
        paint.style = Paint.Style.STROKE
        paint.color = Color.argb((alpha * 0.62f).toInt(), 255, 244, 190)
        paint.strokeWidth = max(1.5f, r * 0.025f)
        canvas.drawArc(-r * 0.30f, -r * 0.18f, r * 0.30f, r * 0.28f, 15f, 150f, false, paint)
        textPaint.textSize = max(12f * density(), r * 0.18f)
        textPaint.alpha = (alpha * 0.78f).toInt()
        canvas.drawText("вспышек: ${m.hp}", 0f, r * 0.82f, textPaint)
    }

    private fun drawSpider(canvas: Canvas, r: Float, m: Monster, alpha: Int) {
        val t = elapsed * 5.5f + m.phase
        paint.style = Paint.Style.STROKE
        paint.strokeCap = Paint.Cap.ROUND
        paint.color = Color.argb(alpha, 4, 4, 10)
        paint.strokeWidth = max(2f * density(), r * 0.055f)
        for (side in listOf(-1f, 1f)) {
            for (i in 0 until 4) {
                val yy = -r * 0.25f + i * r * 0.17f
                val bend = sin(t + i * 1.1f) * r * 0.08f
                val path = Path()
                path.moveTo(side * r * 0.26f, yy)
                path.lineTo(side * (r * 0.68f + bend), yy - r * 0.20f)
                path.lineTo(side * r * 1.02f, yy + r * 0.13f + cos(t + i) * r * 0.03f)
                canvas.drawPath(path, paint)
            }
        }
        paint.style = Paint.Style.FILL
        paint.shader = RadialGradient(0f, -r * 0.10f, r * 0.78f, intArrayOf(Color.argb(alpha, 72, 7, 17), Color.argb(alpha, 0, 0, 0)), floatArrayOf(0f, 1f), Shader.TileMode.CLAMP)
        canvas.drawOval(-r * 0.43f, -r * 0.58f, r * 0.43f, r * 0.58f, paint)
        canvas.drawOval(-r * 0.30f, -r * 0.80f, r * 0.30f, -r * 0.30f, paint)
        paint.shader = null
        paint.color = Color.argb(alpha, 255, 66, 76)
        canvas.drawCircle(-r * 0.12f, -r * 0.58f, r * 0.045f, paint)
        canvas.drawCircle(r * 0.12f, -r * 0.58f, r * 0.045f, paint)
        // Клыки.
        paint.color = Color.argb((alpha * 0.85f).toInt(), 240, 245, 255)
        val fang = Path()
        fang.moveTo(-r * 0.16f, -r * 0.34f); fang.lineTo(-r * 0.08f, -r * 0.16f); fang.lineTo(-r * 0.03f, -r * 0.34f); fang.close()
        canvas.drawPath(fang, paint)
        fang.reset(); fang.moveTo(r * 0.03f, -r * 0.34f); fang.lineTo(r * 0.08f, -r * 0.16f); fang.lineTo(r * 0.16f, -r * 0.34f); fang.close()
        canvas.drawPath(fang, paint)
        textPaint.textSize = max(12f * density(), r * 0.18f)
        textPaint.alpha = (alpha * 0.78f).toInt()
        canvas.drawText("разрезов: ${m.hp}", 0f, r * 0.88f, textPaint)
    }

    private fun drawHp(canvas: Canvas, y: Float, base: Float, m: Monster, alpha: Int) {
        val w = base * 1.25f
        val h = 7f * density()
        paint.style = Paint.Style.FILL
        paint.color = Color.argb((alpha * 0.58f).toInt(), 0, 0, 0)
        canvas.drawRect(-w / 2, y, w / 2, y + h, paint)
        paint.color = if (m.type == MonsterType.FLASH) Color.argb(alpha, 255, 225, 120) else Color.argb(alpha, 255, 70, 85)
        canvas.drawRect(-w / 2, y, -w / 2 + w * (m.hp.toFloat() / m.maxHp), y + h, paint)
    }

    private fun drawParticles(canvas: Canvas) {
        paint.style = Paint.Style.FILL
        for (p in particles) {
            val a = (p.life / p.maxLife).coerceIn(0f, 1f)
            paint.color = Color.argb((a * 230).toInt(), Color.red(p.color), Color.green(p.color), Color.blue(p.color))
            canvas.drawCircle(p.x, p.y, p.size * a + 0.6f, paint)
        }
    }

    private fun drawReticle(canvas: Canvas) {
        paint.style = Paint.Style.STROKE
        paint.color = Color.argb(58, 210, 230, 255)
        paint.strokeWidth = 1.5f * density()
        val cx = width / 2f; val cy = height / 2f; val len = 18f * density()
        canvas.drawLine(cx - len, cy, cx + len, cy, paint)
        canvas.drawLine(cx, cy - len, cx, cy + len, paint)
    }

    private fun drawRadar(canvas: Canvas) {
        val size = 126f * density()
        val cx = width - size / 2f - 12f * density()
        val cy = height - size / 2f - 12f * density()
        val rr = size / 2f - 6f * density()
        paint.style = Paint.Style.FILL
        paint.color = Color.argb(92, 2, 5, 13)
        canvas.drawCircle(cx, cy, rr, paint)
        paint.style = Paint.Style.STROKE
        paint.color = Color.argb(72, 180, 210, 255)
        paint.strokeWidth = 1f * density()
        canvas.drawCircle(cx, cy, rr, paint)
        // Сектор обзора 160° вверх от игрока.
        paint.color = Color.argb(105, 120, 230, 255)
        val path = Path()
        path.moveTo(cx, cy)
        path.arcTo(android.graphics.RectF(cx - rr, cy - rr, cx + rr, cy + rr), -170f, 160f)
        path.close()
        canvas.drawPath(path, paint)
        for (m in monsters) {
            val a = deltaAngle(m.yaw, smoothYaw) * PI.toFloat() / 180f - (PI / 2).toFloat()
            val d = rr * m.dist.coerceIn(0f, 1f)
            paint.style = Paint.Style.FILL
            paint.color = if (m.type == MonsterType.FLASH) Color.argb(235, 255, 220, 110) else Color.argb(235, 255, 60, 80)
            canvas.drawCircle(cx + cos(a) * d, cy + sin(a) * d, 4f * density(), paint)
        }
        paint.style = Paint.Style.FILL
        paint.color = Color.WHITE
        canvas.drawCircle(cx, cy, 2.5f * density(), paint)
    }

    private data class ScreenPos(val x: Float, val y: Float, val scale: Float, val alpha: Float)

    private fun monsterScreen(m: Monster): ScreenPos? {
        val dy = deltaAngle(m.yaw, smoothYaw)
        val dp = m.pitch - smoothPitch
        if (abs(dy) > H_FOV / 2f || abs(dp) > V_FOV / 2f) return null
        val nx = dy / (H_FOV / 2f)
        val ny = dp / (V_FOV / 2f)
        val wobX = sin(elapsed * m.wobble * 2f + m.phase) * 10f * density() * (1f - m.dist)
        val wobY = cos(elapsed * m.wobble * 1.7f + m.phase) * 7f * density() * (1f - m.dist)
        val spawnFade = min(1f, m.age / 0.55f)
        return ScreenPos(
            x = width / 2f + nx * width / 2f + wobX,
            y = height / 2f - ny * height / 2f + wobY,
            scale = lerp(0.45f, 1.85f, 1f - m.dist) * (0.75f + 0.25f * spawnFade),
            alpha = lerp(0.30f, 0.96f, 1f - m.dist) * spawnFade
        )
    }

    /** Точка детектора -> экран с учётом center-crop вертикального кадра камеры. */
    private fun screenPoint(u: Float, v: Float): Pair<Float, Float> {
        if (width <= 0 || height <= 0) return 0f to 0f
        val viewAspect = width.toFloat() / height.toFloat()
        val displayedWidth: Float
        val displayedHeight: Float
        if (videoAspect > viewAspect) {
            displayedHeight = height.toFloat(); displayedWidth = displayedHeight * videoAspect
        } else {
            displayedWidth = width.toFloat(); displayedHeight = displayedWidth / videoAspect
        }
        val offsetX = (width - displayedWidth) / 2f
        val offsetY = (height - displayedHeight) / 2f
        return (offsetX + u.coerceIn(0f, 1f) * displayedWidth) to (offsetY + v.coerceIn(0f, 1f) * displayedHeight)
    }

    private fun distancePointSegment(px: Float, py: Float, x1: Float, y1: Float, x2: Float, y2: Float): Float {
        val vx = x2 - x1; val vy = y2 - y1; val wx = px - x1; val wy = py - y1
        val c1 = vx * wx + vy * wy
        if (c1 <= 0f) return hypot((px - x1).toDouble(), (py - y1).toDouble()).toFloat()
        val c2 = vx * vx + vy * vy
        if (c2 <= c1) return hypot((px - x2).toDouble(), (py - y2).toDouble()).toFloat()
        val t = c1 / c2
        return hypot((px - (x1 + t * vx)).toDouble(), (py - (y1 + t * vy)).toDouble()).toFloat()
    }

    private fun density(): Float = resources.displayMetrics.density

    private fun deltaAngle(a: Float, b: Float): Float {
        var d = a - b
        while (d > 180f) d -= 360f
        while (d < -180f) d += 360f
        return d
    }

    private fun lerp(a: Float, b: Float, t: Float): Float = a + (b - a) * t
}
