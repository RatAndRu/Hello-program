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
import kotlin.math.tan
import kotlin.random.Random

/** Игровой оверлей поверх камеры: монстры, эффекты света/лазера, радар, прицел и частицы. */
class GameView @JvmOverloads constructor(context: Context, attrs: AttributeSet? = null) : View(context, attrs) {
    enum class MonsterType { FLASH, LASER, MORSE, SHIELD_SPIDER, SLIME, SLIME_SMALL, INVISIBLE, STALKER, HEALER, MIRROR, BOSS_REAPER, BOSS_MOTHER }

    enum class Consumable(val icon: String, val title: String) {
        GRENADE("💣", "Граната"), SHIELD("🛡", "Щит"), SLOW("🐌", "Замедление"), RADAR("📡", "Радар"),
        LURE("🎯", "Приманка"), MEDKIT("✚", "Аптечка"), BOOSTER("🔦", "Усилитель"), HOLY("💧", "Св. вода"), SALT("🧂", "Соль");
        val label: String get() = "$icon $title"
    }

    // Только то, чего НЕТ в верхнем HUD: осколки и активный щит. Жизни/счёт там не дублируем.
    data class InventoryState(
        val shards: Int,
        val counts: Map<Consumable, Int>,
        val shieldActive: Boolean
    )

    data class HudState(val timeLeftSec: Int, val lives: Int, val score: Int)

    var listener: Listener? = null

    interface Listener {
        fun onHud(state: HudState)
        fun onGameEnd(win: Boolean, score: Int, elapsedSec: Int)
        fun onToast(text: String)
        fun onInventory(state: InventoryState) {}
        fun onUpgradeChoices(choices: List<String>) {}
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
        var laserInsideUntil: Float = -1f,
        var shieldHp: Int = 0,
        var mirrorBroken: Boolean = false,
        var morseSequence: List<Boolean> = emptyList(),
        var morseIndex: Int = 0,
        var healTimer: Float = 3f,
        var childSpawnTimer: Float = 6f,
        var bossPhaseUntil: Float = 0f,
        var bossLaserPhase: Boolean = false
    ) { val isBoss: Boolean get() = type == MonsterType.BOSS_REAPER || type == MonsterType.BOSS_MOTHER }


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
    private var paused = false
    var use3DModels = true
    var modelView: Monster3DView? = null
    private val sound = SoundEngine()
    private var orientationSmoothingScale = 1f
    private var lastFlashCompletedId = 0L

    private var shards = 0
    private var killsSinceUpgrade = 0
    private var upgradePending = false
    private val consumableCounts = mutableMapOf(
        Consumable.GRENADE to 1, Consumable.SHIELD to 0, Consumable.SLOW to 0,
        Consumable.RADAR to 1, Consumable.LURE to 0, Consumable.MEDKIT to 0,
        Consumable.BOOSTER to 0, Consumable.HOLY to 0, Consumable.SALT to 0
    )
    private var shieldActive = false
    private var slowUntil = -1f
    private var radarUntil = -1f
    private var lureUntil = -1f
    private var lureYaw = 0f
    private var lurePitch = 0f
    private var boostUntil = -1f
    private var saltUntil = -1f
    private val pendingSpawns = mutableListOf<Monster>()
    private val bossSpawnTimes = mutableListOf(60f to MonsterType.BOSS_REAPER, 165f to MonsterType.BOSS_MOTHER)

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
    private var debugTrailExpiresAt = 0L
    private var touchFlashX = 0f
    private var touchFlashY = 0f
    private var touchFlashExpiresAt = 0L
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
        paused = false
        shards = 0; killsSinceUpgrade = 0; upgradePending = false
        consumableCounts[Consumable.GRENADE] = 1; consumableCounts[Consumable.SHIELD] = 0; consumableCounts[Consumable.SLOW] = 0
        consumableCounts[Consumable.RADAR] = 1; consumableCounts[Consumable.LURE] = 0; consumableCounts[Consumable.MEDKIT] = 0
        consumableCounts[Consumable.BOOSTER] = 0; consumableCounts[Consumable.HOLY] = 0; consumableCounts[Consumable.SALT] = 0
        shieldActive = false; slowUntil = -1f; radarUntil = -1f; lureUntil = -1f; boostUntil = -1f; saltUntil = -1f
        pendingSpawns.clear(); bossSpawnTimes.clear(); bossSpawnTimes += 60f to MonsterType.BOSS_REAPER; bossSpawnTimes += 165f to MonsterType.BOSS_MOTHER
        lastFlashCompletedId = detections.flashCompletedId
        previousFlashActive = false
        if (debugTouchMode) detections = FrameDetections()
        debugTrail.clear(); debugTrailExpiresAt = 0L; touchFlashExpiresAt = 0L
        lastFrameMs = 0L
        pushHud(); pushInventory()
        invalidate()
    }

    fun stopGame() {
        running = false
        monsters.clear()
        particles.clear()
        pendingSpawns.clear()
        modelView?.submit(emptyList(), smoothYaw, smoothPitch, elapsed)
        invalidate()
    }

    fun setPaused(value: Boolean) {
        paused = value
        if (!value) lastFrameMs = 0L
        invalidate()
    }

    fun setOrientationSmoothing(scale: Float) {
        orientationSmoothingScale = scale.coerceIn(0.35f, 2.5f)
    }

    override fun onDetachedFromWindow() {
        sound.release()
        super.onDetachedFromWindow()
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
                debugTrail.clear(); debugTrailExpiresAt = 0L
                debugSwipeHitIds.clear()
                debugTrail += event.x to event.y
                parent?.requestDisallowInterceptTouchEvent(true)
            }
            MotionEvent.ACTION_MOVE -> {
                if (hypot((event.x - debugDownX).toDouble(), (event.y - debugDownY).toDouble()) > 14f * density()) debugMoved = true
                val prev = debugTrail.lastOrNull()
                debugTrail += event.x to event.y
                if (debugTrail.size > 80) debugTrail.removeAt(0)
                debugTrailExpiresAt = System.currentTimeMillis() + 400L
                if (prev != null) debugSwipeDamage(prev.first, prev.second, event.x, event.y)
            }
            MotionEvent.ACTION_UP -> {
                val heldMs = System.currentTimeMillis() - debugDownAt
                if (!debugMoved) debugTapDamage(event.x, event.y, isLong = heldMs >= 350L)
                else if (debugTrail.size >= 2) {
                    for (i in 1 until debugTrail.size) {
                        val a = debugTrail[i - 1]; val b = debugTrail[i]
                        debugSwipeDamage(a.first, a.second, b.first, b.second)
                    }
                }
                debugTrailExpiresAt = System.currentTimeMillis() + 250L
            }
            MotionEvent.ACTION_CANCEL -> { debugTrail.clear(); debugTrailExpiresAt = 0L }
        }
        invalidate()
    }

    /** Тап/удержание в сенсорном режиме = стандартная вспышка: короткая или длинная для Морзе. */
    private fun debugTapDamage(x: Float, y: Float, isLong: Boolean = false) {
        touchFlashX = x; touchFlashY = y
        touchFlashExpiresAt = System.currentTimeMillis() + 220L
        // Сначала Морзе: длинное удержание >= 350 мс считается длинным сигналом.
        processMorseSymbol(x, y, isLong)
        if (monsters.any { it.hp <= 0 }) monsters.removeAll { it.hp <= 0 }
        val lightRadius = 0.16f * min(width, height) * if (elapsed < boostUntil) 1.65f else 1f
        val iterator = monsters.iterator()
        while (iterator.hasNext()) {
            val m = iterator.next()
            if (!isFlashVulnerable(m) || !isMonsterHittable(m)) continue
            val screen = monsterScreen(m) ?: continue
            val radius = monsterRadius(m, screen.scale)
            val d = hypot((screen.x - x).toDouble(), (screen.y - y).toDouble())
            if (d < radius + lightRadius * 0.65f && elapsed - m.lastHitAt > 0.18f) {
                hitMonster(m, screen.x, screen.y, radius, DamageSource.FLASH)
                if (m.hp <= 0) iterator.remove()
            }
        }
    }

    /** Свайп в отладке имитирует лазерную линию: каждый паук получает не более одного разреза за свайп. */
    private fun debugSwipeDamage(x1: Float, y1: Float, x2: Float, y2: Float) {
        if (hypot((x2 - x1).toDouble(), (y2 - y1).toDouble()) < 8f * density()) return
        val iterator = monsters.iterator()
        while (iterator.hasNext()) {
            val m = iterator.next()
            if (m.id in debugSwipeHitIds) continue
            val s = monsterScreen(m) ?: continue
            val radius = monsterRadius(m, s.scale)
            if (m.type == MonsterType.MIRROR && !m.mirrorBroken) {
                val rune = screenForAngle(m.yaw + 20f, m.pitch, m.dist)
                if (rune != null && distancePointSegment(rune.x, rune.y, x1, y1, x2, y2) < 38f * density()) {
                    debugSwipeHitIds += m.id; m.mirrorBroken = true; m.hitFlash = 0.25f; sound.runeBreak()
                    listener?.onToast("Зеркальная руна разбита! Теперь — вспышкой")
                }
                continue
            }
            if (!isLaserVulnerable(m) || !isMonsterHittable(m)) continue
            val d = distancePointSegment(s.x, s.y, x1, y1, x2, y2)
            if (d < radius * 0.82f) {
                debugSwipeHitIds += m.id
                if (m.type == MonsterType.SHIELD_SPIDER && m.shieldHp > 0) {
                    m.shieldHp--; m.lastHitAt = elapsed; m.hitFlash = 0.2f; if (m.shieldHp > 0) sound.shieldHit() else sound.shieldBreak()
                    listener?.onToast(if (m.shieldHp > 0) "Щит паука: осталось ${m.shieldHp}" else "Щит паука разрушен!")
                } else {
                    hitMonster(m, s.x, s.y, radius, DamageSource.LASER)
                    if (m.hp <= 0) iterator.remove()
                }
            }
        }
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val now = System.currentTimeMillis()
        val dt = if (lastFrameMs == 0L) 0.016f else min(0.05f, (now - lastFrameMs) / 1000f)
        lastFrameMs = now
        if (running && !paused) update(dt)
        drawScene(canvas)
        if (running) postInvalidateOnAnimation()
    }

    private fun update(dt: Float) {
        elapsed += dt
        hurtFlash = max(0f, hurtFlash - dt * 1.8f)
        updateOrientation(dt)
        updateFlashEdge()
        updateMorseFlashes()
        updateBossSpawns()
        updateSpawning(dt)
        updateMonsters(dt)
        updateParticles(dt)
        hudTick -= dt
        if (hudTick <= 0f) { hudTick = 0.12f; pushHud() }
        if (elapsed >= DURATION_SEC) endGame(true)
    }

    private fun updateOrientation(dt: Float) {
        val k = (1f - Math.pow(0.001, dt.toDouble()).toFloat()) * orientationSmoothingScale
        smoothYaw += deltaAngle(targetYaw, smoothYaw) * k
        smoothPitch += (targetPitch - smoothPitch) * k
    }

    private fun updateFlashEdge() {
        if (debugTouchMode) { flashRising = false; previousFlashActive = false; return }
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
        val pool = mutableListOf<MonsterType>()
        fun add(type: MonsterType, weight: Int) { repeat(weight) { pool += type } }
        add(MonsterType.FLASH, 28); add(MonsterType.LASER, 24)
        if (elapsed > 20f) add(MonsterType.SLIME, 10)
        if (elapsed > 35f) add(MonsterType.INVISIBLE, 8)
        if (elapsed > 50f) add(MonsterType.SHIELD_SPIDER, 9)
        if (elapsed > 65f) add(MonsterType.STALKER, 8)
        if (elapsed > 80f) add(MonsterType.HEALER, 6)
        if (elapsed > 95f) add(MonsterType.MIRROR, 7)
        if (elapsed > 115f) add(MonsterType.MORSE, 7)
        val type = pool.random()
        val hp = when (type) {
            MonsterType.FLASH -> listOf(2, 3, 3, 4).random() + if (progress > 0.72f && Random.nextFloat() < 0.25f) 1 else 0
            MonsterType.LASER -> listOf(2, 2, 3).random()
            MonsterType.MORSE -> 1 // здоровье здесь — одна разгаданная последовательность
            MonsterType.SHIELD_SPIDER -> 3
            MonsterType.SLIME -> 2
            MonsterType.SLIME_SMALL -> 1
            MonsterType.INVISIBLE -> 3
            MonsterType.STALKER -> 3
            MonsterType.HEALER -> 4
            MonsterType.MIRROR -> 3
            MonsterType.BOSS_REAPER, MonsterType.BOSS_MOTHER -> 10
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
        val baseSpeed = when (type) {
            MonsterType.FLASH -> Random.nextFloat().let { 0.030f + it * 0.020f }
            MonsterType.LASER -> Random.nextFloat().let { 0.040f + it * 0.025f }
            MonsterType.SLIME -> Random.nextFloat().let { 0.034f + it * 0.018f }
            MonsterType.STALKER -> Random.nextFloat().let { 0.052f + it * 0.020f }
            MonsterType.HEALER -> 0.026f
            MonsterType.MORSE -> 0.027f
            else -> Random.nextFloat().let { 0.032f + it * 0.020f }
        }
        val sequence = if (type == MonsterType.MORSE) List(4) { Random.nextBoolean() } else emptyList()
        monsters += Monster(
            id = nextMonsterId++, type = type, hp = hp, maxHp = hp,
            yaw = yaw, pitch = pitch,
            dist = Random.nextFloat().let { 0.84f + it * 0.16f },
            speed = baseSpeed * (1f + progress * 0.48f),
            phase = Random.nextFloat().let { it * (PI * 2).toFloat() },
            wobble = Random.nextFloat().let { 0.6f + it * 0.8f },
            shieldHp = if (type == MonsterType.SHIELD_SPIDER) 2 else 0,
            morseSequence = sequence,
            healTimer = Random.nextFloat().let { 2.5f + it * 2f },
            childSpawnTimer = 6f
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
            val visibleNow = monsterScreen(m) != null
            val speedFactor = when {
                elapsed < slowUntil -> 0.48f
                m.type == MonsterType.STALKER && visibleNow -> 0.06f // подкрадывающийся почти стоит под взглядом
                m.type == MonsterType.STALKER -> 1.30f
                else -> 1f
            }
            m.dist -= m.speed * speedFactor * dt
            if (elapsed < saltUntil && m.dist < 0.27f) m.dist = 0.27f
            if (elapsed < lureUntil && !m.isBoss) {
                m.yaw += deltaAngle(lureYaw, m.yaw) * dt * 0.65f
                m.pitch += (lurePitch - m.pitch) * dt * 0.65f
            } else {
                m.yaw += sin(elapsed * 0.55f + m.phase) * dt * 1.25f
                m.pitch = (m.pitch + cos(elapsed * 0.45f + m.phase) * dt * 0.5f).coerceIn(-55f, 55f)
            }
            if (m.type == MonsterType.HEALER) {
                m.healTimer -= dt
                if (m.healTimer <= 0f) {
                    m.healTimer = 4.5f
                    val target = monsters.filter { it !== m && it.hp < it.maxHp }.minByOrNull { it.dist }
                    if (target != null) {
                        target.hp++
                        monsterScreen(target)?.let { spawnParticles(it.x, it.y, 34f * density(), Color.rgb(80, 255, 140), 10) }
                        listener?.onToast("Тёмный лекарь восстановил монстра!")
                    }
                }
            }
            if (m.type == MonsterType.BOSS_MOTHER) {
                m.childSpawnTimer -= dt
                if (m.childSpawnTimer <= 0f && monsters.size < 12) {
                    m.childSpawnTimer = 7f
                    pendingSpawns += Monster(id = nextMonsterId++, type = MonsterType.LASER, hp = 1, maxHp = 1,
                        yaw = m.yaw + Random.nextFloat().let { -18f + it * 36f }, pitch = m.pitch + Random.nextFloat().let { -10f + it * 20f },
                        dist = (m.dist + 0.10f).coerceAtMost(1f), speed = 0.055f, phase = Random.nextFloat() * 6.28f, wobble = 1.1f)
                    listener?.onToast("Мать Пауков выпустила паучка!")
                }
            }
            if (m.type == MonsterType.BOSS_REAPER && elapsed >= m.bossPhaseUntil) {
                m.bossPhaseUntil = elapsed + 6f
                m.bossLaserPhase = !m.bossLaserPhase
                if (m.bossLaserPhase) {
                    // В лазерной фазе Жнец дополнительно требует один морзе-сигнал как ключ: последовательность из 2 символов.
                    if (m.morseSequence.isEmpty()) m.morseSequence = listOf(false, true)
                    m.morseIndex = 0
                }
                listener?.onToast(if (m.bossLaserPhase) "Жнец уязвим к лазеру!" else "Жнец уязвим к вспышкам!")
            }

            val s = monsterScreen(m)
            if (s != null) {
                val radius = monsterRadius(m, s.scale)
                if (isFlashVulnerable(m) && isMonsterHittable(m) && flashRising && flashPoint != null && elapsed - m.lastHitAt > 0.32f) {
                    val d = hypot((s.x - flashPoint.first).toDouble(), (s.y - flashPoint.second).toDouble())
                    val lightRadius = detections.flashRadius * min(width, height) * if (elapsed < boostUntil) 1.65f else 1f
                    if (d < radius + lightRadius * 0.68f) hitMonster(m, s.x, s.y, radius, DamageSource.FLASH)
                }
                if (laserSegment != null && elapsed - m.lastHitAt > 0.38f) {
                    val (a, b) = laserSegment
                    val len = hypot((b.first - a.first).toDouble(), (b.second - a.second).toDouble())
                    if (len > 18f * density()) {
                        val d = distancePointSegment(s.x, s.y, a.first, a.second, b.first, b.second)
                        val inside = d < radius * 0.82f
                        // Зеркальный монстр: сначала лазером бьём не по телу, а по руне рядом.
                        if (m.type == MonsterType.MIRROR && !m.mirrorBroken) {
                            val rune = screenForAngle(m.yaw + 20f, m.pitch, m.dist)
                            if (rune != null && distancePointSegment(rune.x, rune.y, a.first, a.second, b.first, b.second) < 38f * density() && m.lastLaserTrack != detections.laserTrackId) {
                                m.lastLaserTrack = detections.laserTrackId; m.mirrorBroken = true; m.hitFlash = 0.25f
                                spawnParticles(rune.x, rune.y, 38f * density(), Color.rgb(170, 220, 255), 22); sound.runeBreak(); listener?.onToast("Зеркальная руна разбита! Теперь — вспышкой")
                            }
                        } else if (inside && isLaserVulnerable(m) && isMonsterHittable(m) && m.lastLaserTrack != detections.laserTrackId) {
                            m.lastLaserTrack = detections.laserTrackId
                            if (m.type == MonsterType.SHIELD_SPIDER && m.shieldHp > 0) {
                                m.shieldHp--; m.lastHitAt = elapsed; m.hitFlash = 0.2f; if (m.shieldHp > 0) sound.shieldHit() else sound.shieldBreak()
                                spawnParticles(s.x, s.y, radius, Color.rgb(120, 210, 255), 14)
                                listener?.onToast(if (m.shieldHp > 0) "Щит паука: осталось ${m.shieldHp}" else "Щит паука разрушен!")
                            } else hitMonster(m, s.x, s.y, radius, DamageSource.LASER)
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
                if (shieldActive) {
                    shieldActive = false; hurtFlash = 0.55f; sound.shieldBlock(); listener?.onToast("Щит заблокировал атаку!"); pushInventory()
                } else {
                    lives--; hurtFlash = 1f; sound.hurt(); listener?.onToast("Монстр добрался! -1 жизнь")
                }
                pushHud()
                if (lives <= 0) { endGame(false); return }
            }
        }
        if (pendingSpawns.isNotEmpty()) { monsters.addAll(pendingSpawns); pendingSpawns.clear() }
    }

    private fun hitMonster(m: Monster, x: Float, y: Float, radius: Float, source: DamageSource = DamageSource.FLASH) {
        if (m.hp <= 0) return
        m.hp -= 1
        m.lastHitAt = elapsed
        m.hitFlash = 0.20f
        if (source == DamageSource.LASER) sound.hitLaser() else sound.hitFlash()
        spawnParticles(x, y, radius, if (isFlashVulnerable(m) || source == DamageSource.FLASH) Color.rgb(255, 226, 120) else Color.rgb(255, 76, 90), 12)
        if (m.hp <= 0) {
            score++
            val gained = if (m.isBoss) 6 else 1
            shards += gained
            killsSinceUpgrade++
            // Разделяющийся слизень: лазер разрезает его на двух маленьких, их добивают вспышками.
            if (m.type == MonsterType.SLIME && source == DamageSource.LASER) {
                repeat(2) { side ->
                    pendingSpawns += Monster(id = nextMonsterId++, type = MonsterType.SLIME_SMALL, hp = 1, maxHp = 1,
                        yaw = m.yaw + if (side == 0) -13f else 13f, pitch = m.pitch + if (side == 0) -5f else 5f,
                        dist = (m.dist + 0.07f).coerceAtMost(1f), speed = m.speed * 1.15f,
                        phase = Random.nextFloat() * 6.28f, wobble = 1.2f)
                }
                listener?.onToast("Слизень разделился! Добивай вспышками")
            }
            // Добыча: иногда с монстра падает готовый расходник.
            if (!m.isBoss && Random.nextFloat() < 0.16f) {
                val drop = listOf(Consumable.GRENADE, Consumable.SALT, Consumable.BOOSTER, Consumable.LURE, Consumable.SLOW).random()
                addConsumable(drop); listener?.onToast("Выпало: ${drop.label}")
            }
            spawnParticles(x, y, radius, Color.rgb(150, 190, 255), 30)
            sound.death()
            listener?.onToast("Монстр уничтожен! +$gained осколок")
            pushHud(); pushInventory()
            if (m.isBoss) offerUpgrade("Босс повержен! Выбери усиление")
            else if (killsSinceUpgrade >= 10) { killsSinceUpgrade = 0; offerUpgrade("10 монстров уничтожено! Выбери усиление") }
        }
    }

    private fun pushInventory() {
        listener?.onInventory(InventoryState(shards, consumableCounts.toMap(), shieldActive))
    }

    private fun addConsumable(type: Consumable, amount: Int = 1) {
        consumableCounts[type] = (consumableCounts[type] ?: 0) + amount
        pushInventory()
    }

    private fun offerUpgrade(reason: String) {
        if (upgradePending || !running) return
        upgradePending = true
        setPaused(true)
        listener?.onToast(reason)
        listener?.onUpgradeChoices(listOf(
            "💣 +1 световая граната", "🛡 +1 щит", "🐌 +1 замедление", "🎯 +1 приманка", "✚ +1 аптечка", "💧 +1 святая вода"
        ))
    }

    fun applyUpgradeChoice(index: Int) {
        when (index) {
            0 -> addConsumable(Consumable.GRENADE)
            1 -> addConsumable(Consumable.SHIELD)
            2 -> addConsumable(Consumable.SLOW)
            3 -> addConsumable(Consumable.LURE)
            4 -> addConsumable(Consumable.MEDKIT)
            else -> addConsumable(Consumable.HOLY)
        }
        sound.upgrade()
        upgradePending = false
        setPaused(false)
        pushInventory()
    }

    fun cancelUpgradeChoice() {
        upgradePending = false
        setPaused(false)
    }

    fun useConsumable(type: Consumable) {
        if (!running || paused) return
        if (type == Consumable.MEDKIT) {
            if ((consumableCounts[type] ?: 0) <= 0) { listener?.onToast("Нет аптечек"); return }
            if (lives >= 5) { listener?.onToast("Жизни полные"); return }
            consumableCounts[type] = (consumableCounts[type] ?: 0) - 1
            lives++; sound.heal(); listener?.onToast("+1 жизнь"); pushHud(); pushInventory(); return
        }
        if (type == Consumable.SHIELD && shieldActive) { listener?.onToast("Щит уже активен"); return }
        if ((consumableCounts[type] ?: 0) <= 0) { listener?.onToast("Нет расходника: ${type.label}"); return }
        consumableCounts[type] = (consumableCounts[type] ?: 0) - 1
        when (type) {
            Consumable.GRENADE -> {
                var hits = 0
                val iterator = monsters.iterator()
                while (iterator.hasNext()) {
                    val m = iterator.next(); val screen = monsterScreen(m) ?: continue
                    if (!isFlashVulnerable(m) || !isMonsterHittable(m)) continue
                    val radius = monsterRadius(m, screen.scale); hitMonster(m, screen.x, screen.y, radius, DamageSource.GRENADE)
                    hits++
                    if (m.hp <= 0) iterator.remove()
                }
                listener?.onToast("Световая граната: попаданий $hits")
            }
            Consumable.SHIELD -> { shieldActive = true; listener?.onToast("Щит активен") }
            Consumable.SLOW -> { slowUntil = elapsed + 8f; listener?.onToast("Время замедлено на 8 секунд") }
            Consumable.RADAR -> { radarUntil = elapsed + 6f; listener?.onToast("Радарный импульс: все монстры проявлены") }
            Consumable.LURE -> { lureYaw = smoothYaw; lurePitch = smoothPitch; lureUntil = elapsed + 9f; listener?.onToast("Приманка поставлена по взгляду") }
            Consumable.BOOSTER -> { boostUntil = elapsed + 15f; listener?.onToast("Фонарь усилен на 15 секунд") }
            Consumable.HOLY -> {
                val target = monsters.filter { isFlashVulnerable(it) && isMonsterHittable(it) && monsterScreen(it) != null }
                    .minByOrNull { it.dist }
                if (target == null) { consumableCounts[type] = (consumableCounts[type] ?: 0) + 1; listener?.onToast("Нет видимой цели для святой воды") }
                else {
                    val screen = monsterScreen(target)!!; target.hp = 1
                    hitMonster(target, screen.x, screen.y, monsterRadius(target, screen.scale), DamageSource.HOLY)
                    monsters.remove(target); listener?.onToast("Святая вода рассеяла цель")
                }
            }
            Consumable.SALT -> { saltUntil = elapsed + 10f; listener?.onToast("Соль держит монстров на дистанции") }
            else -> Unit
        }
        sound.consumable(type); pushInventory(); invalidate()
    }

    private enum class DamageSource { FLASH, LASER, GRENADE, HOLY, MORSE, DEBUG }

    private fun isFlashVulnerable(m: Monster): Boolean = when (m.type) {
        MonsterType.FLASH, MonsterType.SLIME_SMALL, MonsterType.INVISIBLE -> true
        MonsterType.STALKER -> true
        MonsterType.MORSE -> false // Морзе обрабатывается отдельной последовательностью
        MonsterType.SHIELD_SPIDER -> m.shieldHp <= 0
        MonsterType.MIRROR -> m.mirrorBroken
        MonsterType.BOSS_REAPER -> !m.bossLaserPhase
        else -> false
    }

    private fun isLaserVulnerable(m: Monster): Boolean = when (m.type) {
        MonsterType.LASER, MonsterType.SLIME, MonsterType.HEALER -> true
        MonsterType.SHIELD_SPIDER -> true // пока щит цел, лазер режет щит; после — самого паука тоже можно резать
        MonsterType.BOSS_MOTHER -> true
        MonsterType.BOSS_REAPER -> m.bossLaserPhase
        else -> false
    }

    private fun isMonsterHittable(m: Monster): Boolean {
        if (m.type != MonsterType.INVISIBLE) return true
        if (elapsed < radarUntil) return true
        val cycle = (m.age + m.phase) % 5f
        return cycle < 2.3f
    }

    private fun monsterRadius(m: Monster, scale: Float): Float {
        val base = when (m.type) {
            MonsterType.LASER, MonsterType.SHIELD_SPIDER, MonsterType.HEALER -> 52f
            MonsterType.SLIME, MonsterType.SLIME_SMALL -> 56f
            MonsterType.BOSS_REAPER, MonsterType.BOSS_MOTHER -> 86f
            else -> 62f
        }
        return base * scale * density() * if (m.isBoss) 1.35f else 1f
    }

    private fun updateBossSpawns() {
        val iterator = bossSpawnTimes.iterator()
        while (iterator.hasNext()) {
            val (time, type) = iterator.next()
            if (elapsed >= time) {
                iterator.remove(); spawnBoss(type)
            }
        }
    }

    private fun spawnBoss(type: MonsterType) {
        val hp = if (type == MonsterType.BOSS_REAPER) 12 else 11
        val boss = Monster(
            id = nextMonsterId++, type = type, hp = hp, maxHp = hp,
            yaw = smoothYaw + if (Random.nextBoolean()) -55f else 55f,
            pitch = smoothPitch + Random.nextFloat().let { -12f + it * 24f },
            dist = 1f, speed = if (type == MonsterType.BOSS_REAPER) 0.020f else 0.016f,
            phase = Random.nextFloat().let { it * (PI * 2).toFloat() }, wobble = 0.7f,
            shieldHp = 0, bossPhaseUntil = elapsed + 6f, bossLaserPhase = false
        )
        monsters += boss
        sound.boss()
        listener?.onToast(if (type == MonsterType.BOSS_REAPER) "БОСС: Жнец Тьмы!" else "БОСС: Мать Пауков!")
    }

    private fun updateMorseFlashes() {
        val det = detections
        if (det.flashCompletedId == lastFlashCompletedId) return
        val isLong = det.flashCompletedLong
        lastFlashCompletedId = det.flashCompletedId
        if (debugTouchMode) return // сенсорный режим обрабатывает касания отдельно
        val point = screenPoint(det.flashUAtCompletion, det.flashVAtCompletion)
        processMorseSymbol(point.first, point.second, isLong)
    }

    private fun processMorseSymbol(x: Float, y: Float, isLong: Boolean) {
        // Морзе засчитывается ближайшей видимой морзе-тени в радиусе вспышки.
        var best: Monster? = null; var bestScreen: ScreenPos? = null; var bestDist = Float.MAX_VALUE
        for (m in monsters) {
            if (m.type != MonsterType.MORSE && !(m.type == MonsterType.BOSS_REAPER && m.bossLaserPhase)) continue
            if (m.type == MonsterType.BOSS_REAPER && !m.bossLaserPhase) {
                // У Жнеца морзе-окно совмещено со световой фазой: символы идут вспышками.
            }
            val screen = monsterScreen(m) ?: continue
            val d = hypot((screen.x - x).toDouble(), (screen.y - y).toDouble()).toFloat()
            val radius = monsterRadius(m, screen.scale)
            if (d < radius + 0.17f * min(width, height) && d < bestDist) { best = m; bestScreen = screen; bestDist = d }
        }
        val m = best ?: return
        val screen = bestScreen ?: return
        if (m.morseSequence.isEmpty()) return
        val expected = m.morseSequence[m.morseIndex]
        if (expected == isLong) {
            m.morseIndex++; m.hitFlash = 0.12f; sound.morseProgress()
            if (m.morseIndex >= m.morseSequence.size) {
                m.hp = 1; hitMonster(m, screen.x, screen.y, monsterRadius(m, screen.scale), DamageSource.MORSE)
                monsters.remove(m)
                listener?.onToast("Морзе-код разгадан!")
            } else listener?.onToast("Морзе: ${m.morseIndex}/${m.morseSequence.size}")
        } else {
            m.morseIndex = 0; sound.morseError()
            listener?.onToast("Неверный сигнал — последовательность сброшена")
        }
    }

    private fun endGame(win: Boolean) {
        if (!running) return
        running = false
        if (win) sound.victory() else sound.defeat()
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
        if (use3DModels) {
            modelView?.submit(monsters.map { m ->
                val screen = monsterScreen(m)
                MonsterModelSnapshot(
                    type = m.type, yaw = m.yaw, pitch = m.pitch, dist = m.dist, phase = m.phase, age = m.age,
                    alpha = (screen?.alpha ?: 0.75f) * visibilityAlpha(m),
                    shieldActive = m.shieldHp > 0 || (m.type == MonsterType.MIRROR && !m.mirrorBroken),
                    boss = m.isBoss
                )
            }, smoothYaw, smoothPitch, elapsed)
        } else modelView?.submit(emptyList(), smoothYaw, smoothPitch, elapsed)
        val sorted = monsters.sortedByDescending { it.dist }
        for (m in sorted) drawMonster(canvas, m)
        drawEdgeIndicators(canvas)
        drawActiveEffects(canvas)
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
        if (debugTouchMode) {
            if (System.currentTimeMillis() < touchFlashExpiresAt) {
                val r = 0.16f * min(width, height) * 1.55f
                paint.style = Paint.Style.FILL
                paint.shader = RadialGradient(touchFlashX, touchFlashY, r, intArrayOf(Color.argb(110, 255, 246, 180), Color.argb(48, 255, 220, 110), Color.TRANSPARENT), floatArrayOf(0f, 0.45f, 1f), Shader.TileMode.CLAMP)
                canvas.drawCircle(touchFlashX, touchFlashY, r, paint)
                paint.shader = null
                paint.style = Paint.Style.STROKE
                paint.strokeWidth = 2f * density()
                paint.color = Color.argb(245, 255, 255, 220)
                canvas.drawCircle(touchFlashX, touchFlashY, r * 0.62f, paint)
            }
            return
        }
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
        if (debugTrailExpiresAt > 0L && System.currentTimeMillis() > debugTrailExpiresAt) { debugTrail.clear(); debugTrailExpiresAt = 0L; return }
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
        val base = if (use3DModels && s.visualRadius > 1f) s.visualRadius else (if (m.type == MonsterType.FLASH) 76f else 66f) * s.scale * density()
        canvas.save()
        canvas.translate(s.x, s.y)
        val alpha = (s.alpha * visibilityAlpha(m) * 255).toInt().coerceIn(0, 255)
        if (!use3DModels) {
            if (m.hitFlash > 0f) paint.setShadowLayer(30f * density(), 0f, 0f, Color.argb(alpha, 255, 255, 255))
            when (m.type) {
                MonsterType.FLASH, MonsterType.MORSE, MonsterType.INVISIBLE, MonsterType.MIRROR, MonsterType.STALKER, MonsterType.BOSS_REAPER -> drawWraith(canvas, base, m, alpha)
                else -> drawSpider(canvas, base, m, alpha)
            }
            paint.clearShadowLayer()
        }
        drawMonsterStatus(canvas, base, m, alpha)
        if (use3DModels) drawTypeLabel(canvas, base, m, alpha)
        canvas.restore()
        drawMonsterExtras(canvas, m, s)
    }

    /** Только особая механика под моделью. Обычное HP не дублируем текстом: его показывает сегментная полоска выше. */
    private fun drawTypeLabel(canvas: Canvas, base: Float, m: Monster, alpha: Int) {
        val label = when (m.type) {
            MonsterType.MORSE -> m.morseSequence.joinToString(" ") { if (it) "—" else "●" } + "  ${m.morseIndex}/${m.morseSequence.size}"
            MonsterType.SHIELD_SPIDER -> if (m.shieldHp > 0) "🛡 щит ${m.shieldHp}" else ""
            MonsterType.MIRROR -> if (m.mirrorBroken) "руна разбита" else "лазером по руне"
            MonsterType.BOSS_REAPER -> if (m.bossLaserPhase) "ЖНЕЦ · фаза лазера/Морзе" else "ЖНЕЦ · фаза вспышек"
            MonsterType.BOSS_MOTHER -> "МАТЬ ПАУКОВ"
            else -> ""
        }
        if (label.isBlank()) return
        textPaint.alpha = (alpha * 0.92f).toInt()
        textPaint.textSize = max(11f * density(), base * 0.15f)
        canvas.drawText(label, 0f, base * 1.12f, textPaint)
        if (m.type == MonsterType.MORSE) {
            textPaint.textSize = max(10f * density(), base * 0.12f)
            canvas.drawText("● короткая · — длинная", 0f, base * 1.30f, textPaint)
        }
    }

    /** Компактная сегментная полоска HP строго над проекцией модели; количество сегментов = max HP. */
    private fun drawMonsterStatus(canvas: Canvas, base: Float, m: Monster, alpha: Int) {
        val total = (m.maxHp + if (m.type == MonsterType.SHIELD_SPIDER) m.shieldHp else 0).coerceAtLeast(1)
        val filled = (m.hp + if (m.type == MonsterType.SHIELD_SPIDER) m.shieldHp else 0).coerceAtMost(total)
        val w = max(34f * density(), base * 1.05f)
        val segW = w / total
        val h = max(4f * density(), base * 0.065f)
        val y = -base * 1.12f
        paint.style = Paint.Style.FILL
        for (i in 0 until total) {
            val shieldSegment = m.type == MonsterType.SHIELD_SPIDER && i >= m.hp
            paint.color = when {
                i >= filled -> Color.argb((alpha * 0.30f).toInt(), 25, 30, 45)
                shieldSegment -> Color.argb(alpha, 105, 205, 255)
                m.type == MonsterType.FLASH || m.type == MonsterType.MORSE -> Color.argb(alpha, 255, 220, 110)
                else -> Color.argb(alpha, 255, 72, 88)
            }
            val left = -w / 2f + i * segW + 1f
            canvas.drawRect(left, y, left + segW - 2f, y + h, paint)
        }
        // Боссам — тонкая рамка, чтобы полоска читалась как boss-bar.
        if (m.isBoss) {
            paint.style = Paint.Style.STROKE; paint.strokeWidth = 1.2f * density(); paint.color = Color.argb(alpha, 255, 205, 100)
            canvas.drawRect(-w / 2f, y - 2f, w / 2f, y + h + 2f, paint)
        }
    }

    private fun drawMonsterExtras(canvas: Canvas, m: Monster, s: ScreenPos) {
        if (m.type == MonsterType.MIRROR && !m.mirrorBroken) {
            val rune = screenForAngle(m.yaw + 20f, m.pitch, m.dist) ?: return
            paint.style = Paint.Style.STROKE
            paint.color = Color.argb(230, 170, 225, 255)
            paint.strokeWidth = 2.4f * density()
            val r = 22f * density() * s.scale
            val path = Path()
            path.moveTo(rune.x, rune.y - r); path.lineTo(rune.x + r, rune.y); path.lineTo(rune.x, rune.y + r); path.lineTo(rune.x - r, rune.y); path.close()
            canvas.drawPath(path, paint)
            textPaint.alpha = 220; textPaint.textSize = 13f * density()
            canvas.drawText("РУНА", rune.x, rune.y - r - 8f * density(), textPaint)
        }
        if (m.type == MonsterType.HEALER) {
            textPaint.alpha = 210; textPaint.textSize = 12f * density()
            // Подпись лекаря видна и в 2D, и поверх 3D.
            canvas.drawText("✚", s.x, s.y - monsterRadius(m, s.scale) * 1.25f, textPaint)
        }
    }

    private fun drawActiveEffects(canvas: Canvas) {
        textPaint.textSize = 13f * density(); textPaint.alpha = 230
        val notes = mutableListOf<String>()
        if (shieldActive) notes += "🛡 Щит активен"
        if (elapsed < slowUntil) notes += "🐌 Замедление: ${(slowUntil - elapsed).toInt()}с"
        if (elapsed < radarUntil) notes += "📡 Радар: ${(radarUntil - elapsed).toInt()}с"
        if (elapsed < lureUntil) notes += "🎯 Приманка: ${(lureUntil - elapsed).toInt()}с"
        if (elapsed < boostUntil) notes += "🔦 Усилитель: ${(boostUntil - elapsed).toInt()}с"
        if (elapsed < saltUntil) notes += "🧂 Соль: ${(saltUntil - elapsed).toInt()}с"
        notes.forEachIndexed { i, note -> canvas.drawText(note, width / 2f, height - (142f + i * 20f) * density(), textPaint) }
        if (elapsed < saltUntil) {
            paint.style = Paint.Style.STROKE; paint.color = Color.argb(150, 255, 255, 230); paint.strokeWidth = 2f * density()
            canvas.drawCircle(width / 2f, height / 2f, min(width, height) * 0.34f, paint)
        }
    }

    private fun drawEdgeIndicators(canvas: Canvas) {
        paint.style = Paint.Style.FILL
        textPaint.textSize = 15f * density(); textPaint.alpha = 235
        for (m in monsters) {
            val dy = deltaAngle(m.yaw, smoothYaw)
            val dp = m.pitch - smoothPitch
            if (abs(dy) <= H_FOV / 2f && abs(dp) <= V_FOV / 2f) continue
            val behind = abs(dy) > 105f
            val x = when { behind -> width / 2f; dy < 0f -> 24f * density(); else -> width - 24f * density() }
            val y = (height / 2f - (dp.coerceIn(-70f, 70f) / 70f) * height * 0.36f).coerceIn(70f * density(), height - 90f * density())
            paint.color = if (m.type == MonsterType.LASER || m.type == MonsterType.SHIELD_SPIDER || m.type == MonsterType.BOSS_MOTHER) Color.argb(220, 255, 70, 85) else Color.argb(220, 255, 220, 110)
            val arrow = when { behind -> "▼ СЗАДИ"; dy < 0f -> "◀"; else -> "▶" }
            canvas.drawText(arrow, x, y, textPaint)
        }
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

    private data class ScreenPos(val x: Float, val y: Float, val scale: Float, val alpha: Float, val visualRadius: Float = 0f)

    private fun visibilityAlpha(m: Monster): Float {
        if (m.type != MonsterType.INVISIBLE) return 1f
        if (elapsed < radarUntil) return 1f
        val cycle = (m.age + m.phase) % 5f
        return if (cycle < 2.3f) 1f else 0.10f
    }

    /** Единая с OpenGL перспективная проекция: x=tan(yaw)/tan(80°), y=tan(pitch)/tan(45°). */
    private fun projected(nxTan: Float, nyTan: Float, dist: Float, boss: Boolean, spawnFade: Float = 1f): ScreenPos? {
        if (abs(nxTan) > 1f || abs(nyTan) > 1f) return null
        // Те же depth/scale, что в Monster3DView: интерфейс буквально приклеен к центру и размеру модели.
        val depth = lerp(7.2f, 2.4f, 1f - dist)
        val worldScale = lerp(0.55f, 1.55f, 1f - dist) * if (boss) 1.9f else 1f
        val visualRadius = height * (1.02f * worldScale) / (2f * depth * tan(Math.toRadians(45.0)).toFloat())
        return ScreenPos(
            x = width / 2f + nxTan * width / 2f,
            y = height / 2f - nyTan * height / 2f,
            scale = lerp(0.45f, 1.85f, 1f - dist) * (0.75f + 0.25f * spawnFade),
            alpha = lerp(0.30f, 0.96f, 1f - dist) * spawnFade,
            visualRadius = visualRadius * (0.75f + 0.25f * spawnFade)
        )
    }

    private fun tangentProjection(dy: Float, dp: Float): Pair<Float, Float> =
        (tan(Math.toRadians(dy.toDouble())) / tan(Math.toRadians(80.0))).toFloat() to
            (tan(Math.toRadians(dp.toDouble())) / tan(Math.toRadians(45.0))).toFloat()

    private fun screenForAngle(yaw: Float, pitch: Float, dist: Float): ScreenPos? {
        val dy = deltaAngle(yaw, smoothYaw)
        val dp = pitch - smoothPitch
        if (abs(dy) > H_FOV / 2f || abs(dp) > V_FOV / 2f) return null
        val (nx, ny) = tangentProjection(dy, dp)
        return projected(nx, ny, dist, boss = false)
    }

    private fun monsterScreen(m: Monster): ScreenPos? {
        val dy = deltaAngle(m.yaw, smoothYaw)
        val dp = m.pitch - smoothPitch
        if (abs(dy) > H_FOV / 2f || abs(dp) > V_FOV / 2f) return null
        val (nx, ny) = tangentProjection(dy, dp)
        // Никакого отдельного wobble у интерфейса: покачивание рисует сама 3D-модель,
        // а HP/статус обязаны оставаться на её projected-центре.
        val spawnFade = min(1f, m.age / 0.55f)
        return projected(nx, ny, m.dist, m.isBoss, spawnFade)
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
