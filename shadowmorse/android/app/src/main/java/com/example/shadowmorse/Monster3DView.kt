package com.example.shadowmorse

import android.content.Context
import android.graphics.PixelFormat
import android.opengl.GLES20
import android.opengl.GLSurfaceView
import android.opengl.Matrix
import android.util.AttributeSet
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.FloatBuffer
import javax.microedition.khronos.egl.EGLConfig
import javax.microedition.khronos.opengles.GL10
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.sin

/** Снимок монстра для OpenGL: игровая логика остаётся в GameView, здесь только настоящая 3D-геометрия. */
data class MonsterModelSnapshot(
    val type: GameView.MonsterType,
    val yaw: Float,
    val pitch: Float,
    val dist: Float,
    val phase: Float,
    val age: Float,
    val alpha: Float,
    val shieldActive: Boolean,
    val boss: Boolean
)

/**
 * Простые узнаваемые low-poly 3D-модели на чистом OpenGL ES 2.0 без внешних файлов:
 * призрак — тело-конус со сферой и глазами, паук — сферы и подвижные лапы-параллелепипеды,
 * слизень — пульсирующая сфера, боссы — увеличенные составные силуэты.
 */
class Monster3DView @JvmOverloads constructor(context: Context, attrs: AttributeSet? = null) : GLSurfaceView(context, attrs) {
    private val renderer3D = Renderer3D()

    init {
        setEGLContextClientVersion(2)
        setEGLConfigChooser(8, 8, 8, 8, 16, 0)
        holder.setFormat(PixelFormat.TRANSLUCENT)
        setZOrderOnTop(true)
        setRenderer(renderer3D)
        renderMode = RENDERMODE_CONTINUOUSLY
    }

    fun submit(models: List<MonsterModelSnapshot>, viewYaw: Float, viewPitch: Float, elapsed: Float) {
        renderer3D.submit(models, viewYaw, viewPitch, elapsed)
    }

    fun setModelsEnabled(enabled: Boolean) {
        visibility = if (enabled) VISIBLE else GONE
        if (enabled) onResume() else onPause()
    }

    private class Renderer3D : Renderer {
        @Volatile private var models: List<MonsterModelSnapshot> = emptyList()
        @Volatile private var viewYaw = 0f
        @Volatile private var viewPitch = 0f
        @Volatile private var elapsed = 0f

        private var program = 0
        private var positionHandle = 0
        private var normalHandle = 0
        private var mvpHandle = 0
        private var modelHandle = 0
        private var colorHandle = 0
        private var alphaHandle = 0

        private lateinit var sphere: Mesh
        private lateinit var cone: Mesh
        private lateinit var box: Mesh

        private val projection = FloatArray(16)
        private val view = FloatArray(16)
        private val model = FloatArray(16)
        private val mvp = FloatArray(16)
        private val temp = FloatArray(16)

        fun submit(newModels: List<MonsterModelSnapshot>, yaw: Float, pitch: Float, time: Float) {
            models = newModels
            viewYaw = yaw
            viewPitch = pitch
            elapsed = time
        }

        override fun onSurfaceCreated(gl: GL10?, config: EGLConfig?) {
            GLES20.glClearColor(0f, 0f, 0f, 0f)
            GLES20.glEnable(GLES20.GL_DEPTH_TEST)
            GLES20.glEnable(GLES20.GL_BLEND)
            GLES20.glBlendFunc(GLES20.GL_SRC_ALPHA, GLES20.GL_ONE_MINUS_SRC_ALPHA)
            program = buildProgram()
            positionHandle = GLES20.glGetAttribLocation(program, "aPosition")
            normalHandle = GLES20.glGetAttribLocation(program, "aNormal")
            mvpHandle = GLES20.glGetUniformLocation(program, "uMvp")
            modelHandle = GLES20.glGetUniformLocation(program, "uModel")
            colorHandle = GLES20.glGetUniformLocation(program, "uColor")
            alphaHandle = GLES20.glGetUniformLocation(program, "uAlpha")
            sphere = createSphere(20, 14)
            cone = createCone(20)
            box = createBox()
        }

        override fun onSurfaceChanged(gl: GL10?, width: Int, height: Int) {
            GLES20.glViewport(0, 0, width, height)
            val aspect = if (height == 0) 1f else width.toFloat() / height.toFloat()
            // ТА ЖЕ проекция, что у 2D-интерфейса GameView: горизонтальный FOV 160°, вертикальный 90°.
            // Раньше здесь был перспективный FOV 90° только по вертикали, поэтому HP/подписи
            // (линейная проекция GameView) уезжали от моделей тем сильнее, чем дальше от центра.
            val near = 0.1f
            val right = kotlin.math.tan(Math.toRadians(80.0)).toFloat() * near
            val top = kotlin.math.tan(Math.toRadians(45.0)).toFloat() * near
            Matrix.frustumM(projection, 0, -right, right, -top, top, near, 30f)
        }

        override fun onDrawFrame(gl: GL10?) {
            GLES20.glClear(GLES20.GL_COLOR_BUFFER_BIT or GLES20.GL_DEPTH_BUFFER_BIT)
            GLES20.glUseProgram(program)
            Matrix.setLookAtM(view, 0, 0f, 0f, 0f, 0f, 0f, -1f, 0f, 1f, 0f)
            val sorted = models.sortedByDescending { it.dist }
            for (m in sorted) drawMonster(m)
        }

        private fun drawMonster(m: MonsterModelSnapshot) {
            val dy = deltaAngle(m.yaw, viewYaw)
            val dp = m.pitch - viewPitch
            if (kotlin.math.abs(dy) > 80f || kotlin.math.abs(dp) > 45f) return
            val dyRad = Math.toRadians(dy.toDouble()).toFloat()
            val dpRad = Math.toRadians(dp.toDouble()).toFloat()
            val depth = lerp(7.2f, 2.4f, 1f - m.dist)
            val x = sin(dyRad) * cos(dpRad) * depth
            val y = sin(dpRad) * depth
            val z = -cos(dyRad) * cos(dpRad) * depth
            val baseScale = lerp(0.55f, 1.55f, 1f - m.dist) * if (m.boss) 1.9f else 1f
            val bob = sin(elapsed * 2.2f + m.phase) * 0.08f
            when (m.type) {
                GameView.MonsterType.FLASH -> drawWraith(x, y + bob, z, baseScale, m, darkBlue = false)
                GameView.MonsterType.MORSE -> { drawWraith(x, y + bob, z, baseScale, m, darkBlue = true); drawMorseAntenna(x, y + bob, z, baseScale, m) }
                GameView.MonsterType.INVISIBLE -> drawWraith(x, y + bob, z, baseScale, m, darkBlue = true)
                GameView.MonsterType.LASER -> drawSpider(x, y, z, baseScale, m, body = floatArrayOf(0.05f, 0.01f, 0.04f))
                GameView.MonsterType.SHIELD_SPIDER -> { drawSpider(x, y, z, baseScale, m, body = floatArrayOf(0.08f, 0.02f, 0.10f)); if (m.shieldActive) drawShield(x, y, z, baseScale, m) }
                GameView.MonsterType.SLIME, GameView.MonsterType.SLIME_SMALL -> drawSlime(x, y + bob * 0.5f, z, baseScale * if (m.type == GameView.MonsterType.SLIME_SMALL) 0.55f else 1f, m)
                GameView.MonsterType.STALKER -> drawStalker(x, y, z, baseScale, m)
                GameView.MonsterType.HEALER -> { drawSpider(x, y, z, baseScale, m, body = floatArrayOf(0.02f, 0.10f, 0.08f)); drawHealerCross(x, y, z, baseScale, m) }
                GameView.MonsterType.MIRROR -> { drawWraith(x, y + bob, z, baseScale, m, darkBlue = true); drawMirrorDisc(x, y + bob, z, baseScale, m) }
                GameView.MonsterType.BOSS_REAPER -> drawReaper(x, y + bob, z, baseScale, m)
                GameView.MonsterType.BOSS_MOTHER -> drawSpider(x, y, z, baseScale, m, body = floatArrayOf(0.10f, 0.01f, 0.05f))
            }
        }

        private fun drawWraith(x: Float, y: Float, z: Float, s: Float, m: MonsterModelSnapshot, darkBlue: Boolean) {
            val body = if (darkBlue) floatArrayOf(0.10f, 0.13f, 0.30f) else floatArrayOf(0.23f, 0.28f, 0.48f)
            // Голова-сфера и юбка-конус дают узнаваемый призрачный силуэт.
            val sway = sin(elapsed * 2.6f + m.phase) * 0.05f * s
            val breathe = 1f + sin(elapsed * 3.1f + m.phase) * 0.035f
            // Многослойный силуэт: капюшон, голова, плечи и рваный подол из отдельных лоскутов.
            drawMesh(cone, x, y + 0.34f * s, z - 0.03f * s, s * 0.66f * breathe, s * 0.78f, s * 0.52f, 180f, body, m.alpha * 0.96f)
            drawMesh(sphere, x, y + 0.28f * s, z, s * 0.50f * breathe, s * 0.60f, s * 0.44f, 0f, body, m.alpha)
            drawMesh(cone, x, y - 0.30f * s, z, s * 0.74f, s * 0.98f, s * 0.58f, 180f, body, m.alpha * 0.90f)
            drawMesh(sphere, x, y + 0.05f * s, z + 0.05f * s, s * 0.42f, s * 0.52f, s * 0.36f, 0f, floatArrayOf(body[0]*1.25f, body[1]*1.25f, body[2]*1.25f), m.alpha * 0.85f)
            for (i in -2..2) {
                val flap = sin(elapsed * 4.2f + m.phase + i * 1.35f) * 0.09f * s
                drawMesh(cone, x + i * 0.19f * s, y - 0.72f * s + flap, z, s * 0.13f, s * (0.32f + (i + 2) * 0.025f), s * 0.10f, 180f + i * 5f, body, m.alpha * 0.82f)
            }
            // Руки с когтями медленно тянутся к игроку.
            for (side in listOf(-1f, 1f)) {
                val reach = sin(elapsed * 2.1f + m.phase + side) * 0.06f * s
                drawMesh(box, x + side * 0.55f * s, y + 0.02f * s, z + 0.16f * s, s * 0.10f, s * 0.62f, s * 0.10f, side * (22f + reach * 30f), body, m.alpha)
                for (claw in -1..1) drawMesh(cone, x + side * (0.68f + claw * 0.065f) * s, y - 0.34f * s, z + 0.28f * s + reach, s * 0.035f, s * 0.22f, s * 0.035f, 118f, floatArrayOf(.82f,.86f,.95f), m.alpha)
            }
            // Тёмный провал лица, светящиеся глаза с бликом и рот.
            drawMesh(sphere, x, y + 0.30f * s, z + 0.39f * s, s * 0.34f, s * 0.40f, s * 0.10f, 0f, floatArrayOf(0.005f, 0.005f, 0.02f), m.alpha * 0.92f)
            val eye = floatArrayOf(1f, 0.88f, 0.45f)
            val blink = if (sin(elapsed * 0.75f + m.phase * 3f) > -0.96f) 1f else 0.18f
            for (side in listOf(-1f, 1f)) {
                drawMesh(sphere, x + side * 0.16f * s + sway * .2f, y + 0.37f * s, z + 0.46f * s, s * 0.075f, s * 0.05f * blink, s * 0.04f, 0f, eye, m.alpha)
                drawMesh(sphere, x + side * 0.16f * s, y + 0.39f * s, z + 0.50f * s, s * 0.022f, s * 0.018f, s * 0.016f, 0f, floatArrayOf(1f,1f,1f), m.alpha)
            }
            drawMesh(sphere, x, y + 0.13f * s, z + 0.47f * s, s * 0.11f, s * (0.16f + sin(elapsed*2.4f+m.phase)*0.025f), s * 0.04f, 0f, floatArrayOf(0f,0f,0.01f), m.alpha)
        }

        private fun drawSpider(x: Float, y: Float, z: Float, s: Float, m: MonsterModelSnapshot, body: FloatArray) {
            // Восемь подвижных лап: два поворота в противоположных фазах.
            val legColor = floatArrayOf(0.01f, 0.01f, 0.03f)
            for (side in listOf(-1f, 1f)) {
                for (i in 0 until 4) {
                    val wave = sin(elapsed * 6f + m.phase + i * 0.9f) * 14f
                    val ly = y + (0.22f - i * 0.13f) * s
                    drawMesh(box, x + side * 0.55f * s, ly, z, s * 0.55f, s * 0.045f, s * 0.045f, side * (24f + wave), legColor, m.alpha)
                    drawMesh(box, x + side * 0.92f * s, ly - 0.13f * s, z, s * 0.42f, s * 0.04f, s * 0.04f, side * (-32f - wave), legColor, m.alpha)
                }
            }
            drawMesh(sphere, x, y, z, s * 0.48f, s * 0.62f, s * 0.42f, 0f, body, m.alpha)
            drawMesh(sphere, x, y + 0.42f * s, z + 0.05f * s, s * 0.31f, s * 0.27f, s * 0.27f, 0f, body, m.alpha)
            val eye = floatArrayOf(1f, 0.12f, 0.16f)
            drawMesh(sphere, x - 0.12f * s, y + 0.46f * s, z + 0.28f * s, s * 0.045f, s * 0.045f, s * 0.035f, 0f, eye, m.alpha)
            drawMesh(sphere, x + 0.12f * s, y + 0.46f * s, z + 0.28f * s, s * 0.045f, s * 0.045f, s * 0.035f, 0f, eye, m.alpha)
            // Шесть дополнительных глаз, клыки-хелицеры и предупреждающий узор на брюшке.
            for (i in -1..1) drawMesh(sphere, x + i * 0.13f * s, y + 0.34f * s, z + 0.28f * s, s * 0.032f, s * 0.032f, s * 0.026f, 0f, eye, m.alpha)
            for (side in listOf(-1f, 1f)) {
                val bite = sin(elapsed * 5.2f + m.phase) * 4f
                drawMesh(cone, x + side * 0.13f * s, y + 0.23f * s, z + 0.30f * s, s * 0.045f, s * 0.24f, s * 0.045f, 155f + side * bite, floatArrayOf(.78f,.82f,.9f), m.alpha)
                drawMesh(sphere, x + side * 0.22f * s, y - 0.10f * s, z - 0.22f * s, s * 0.10f, s * 0.055f, s * 0.06f, 0f, floatArrayOf(.65f,.08f,.12f), m.alpha * .75f)
            }
            drawMesh(sphere, x, y + 0.10f * s, z - 0.30f * s, s * 0.22f, s * 0.30f, s * 0.10f, 0f, floatArrayOf(.45f,.03f,.08f), m.alpha * .70f)
            if (m.type == GameView.MonsterType.BOSS_MOTHER) {
                drawMesh(sphere, x, y - 0.28f * s, z - 0.35f * s, s * 0.55f, s * 0.48f, s * 0.52f, 0f, floatArrayOf(0.22f, 0.03f, 0.08f), m.alpha)
            }
        }

        private fun drawSlime(x: Float, y: Float, z: Float, s: Float, m: MonsterModelSnapshot) {
            val pulse = 1f + sin(elapsed * 4.5f + m.phase) * 0.10f
            drawMesh(sphere, x, y, z, s * 0.62f * pulse, s * 0.48f / pulse, s * 0.55f, 0f, floatArrayOf(0.05f, 0.65f, 0.25f), m.alpha * 0.88f)
            drawMesh(sphere, x, y + 0.03f * s, z + 0.08f * s, s * 0.25f, s * 0.20f, s * 0.20f, 0f, floatArrayOf(0.55f, 1f, 0.65f), m.alpha)
            // Ядро и всплывающие пузырьки внутри тела.
            drawMesh(sphere, x + sin(elapsed*.9f+m.phase)*.08f*s, y, z+.12f*s, s*.16f, s*.13f, s*.13f, 0f, floatArrayOf(.75f,1f,.55f), m.alpha*.9f)
            for (i in 0 until 4) {
                val rise = ((elapsed*.22f + i*.27f + m.phase*.03f) % 1f)
                drawMesh(sphere, x + sin(i*2.2f+m.phase)*.28f*s, y + (-.22f+rise*.45f)*s, z+.30f*s, s*(.025f+rise*.025f), s*(.025f+rise*.025f), s*.02f, 0f, floatArrayOf(.8f,1f,.85f), m.alpha*.65f)
            }
            drawMesh(sphere, x - 0.18f * s, y + 0.18f * s, z + 0.42f * s, s * 0.05f, s * 0.07f, s * 0.04f, 0f, floatArrayOf(0f, 0.08f, 0.02f), m.alpha)
            drawMesh(sphere, x + 0.18f * s, y + 0.18f * s, z + 0.42f * s, s * 0.05f, s * 0.07f, s * 0.04f, 0f, floatArrayOf(0f, 0.08f, 0.02f), m.alpha)
        }

        private fun drawStalker(x: Float, y: Float, z: Float, s: Float, m: MonsterModelSnapshot) {
            drawMesh(cone, x, y, z, s * 0.55f, s * 1.35f, s * 0.42f, 180f, floatArrayOf(0.03f, 0.03f, 0.09f), m.alpha)
            drawMesh(sphere, x, y + 0.62f * s, z, s * 0.28f, s * 0.36f, s * 0.25f, 0f, floatArrayOf(0.05f, 0.05f, 0.14f), m.alpha)
            val eye = floatArrayOf(0.65f, 0.95f, 1f)
            drawMesh(sphere, x - 0.10f * s, y + 0.68f * s, z + 0.22f * s, s * 0.04f, s * 0.09f, s * 0.035f, 0f, eye, m.alpha)
            drawMesh(sphere, x + 0.10f * s, y + 0.68f * s, z + 0.22f * s, s * 0.04f, s * 0.09f, s * 0.035f, 0f, eye, m.alpha)
            for (side in listOf(-1f, 1f)) drawMesh(box, x + side * 0.42f * s, y - 0.55f * s, z, s * 0.05f, s * 0.85f, s * 0.05f, side * 12f, floatArrayOf(0f, 0f, 0.02f), m.alpha)
        }

        private fun drawReaper(x: Float, y: Float, z: Float, s: Float, m: MonsterModelSnapshot) {
            drawWraith(x, y, z, s, m, darkBlue = true)
            val bone = floatArrayOf(0.82f, 0.86f, 0.92f)
            // Рога и коса из конусов/планок: силуэт жнеца читается даже без текстур.
            drawMesh(cone, x - 0.38f * s, y + 0.62f * s, z, s * 0.10f, s * 0.42f, s * 0.10f, -28f, bone, m.alpha)
            drawMesh(cone, x + 0.38f * s, y + 0.62f * s, z, s * 0.10f, s * 0.42f, s * 0.10f, 28f, bone, m.alpha)
            drawMesh(box, x + 0.78f * s, y + 0.05f * s, z + 0.12f * s, s * 0.05f, s * 1.15f, s * 0.05f, 18f, floatArrayOf(0.25f, 0.16f, 0.08f), m.alpha)
            drawMesh(box, x + 0.98f * s, y + 0.58f * s, z + 0.12f * s, s * 0.52f, s * 0.07f, s * 0.03f, -18f, bone, m.alpha)
        }

        private fun drawShield(x: Float, y: Float, z: Float, s: Float, m: MonsterModelSnapshot) {
            drawMesh(sphere, x, y + 0.1f * s, z + 0.36f * s, s * 0.74f, s * 0.74f, s * 0.18f, 0f, floatArrayOf(0.35f, 0.75f, 1f), m.alpha * 0.38f)
        }

        private fun drawMirrorDisc(x: Float, y: Float, z: Float, s: Float, m: MonsterModelSnapshot) {
            drawMesh(sphere, x + 0.52f * s, y + 0.05f * s, z + 0.38f * s, s * 0.30f, s * 0.38f, s * 0.06f, 0f, floatArrayOf(0.72f, 0.88f, 1f), m.alpha * 0.85f)
        }

        private fun drawHealerCross(x: Float, y: Float, z: Float, s: Float, m: MonsterModelSnapshot) {
            val c = floatArrayOf(0.25f, 1f, 0.55f)
            drawMesh(box, x, y + 0.82f * s, z + 0.18f * s, s * 0.10f, s * 0.42f, s * 0.05f, 0f, c, m.alpha)
            drawMesh(box, x, y + 0.82f * s, z + 0.18f * s, s * 0.34f, s * 0.10f, s * 0.05f, 0f, c, m.alpha)
        }

        private fun drawMorseAntenna(x: Float, y: Float, z: Float, s: Float, m: MonsterModelSnapshot) {
            drawMesh(box, x, y + 0.82f * s, z, s * 0.035f, s * 0.45f, s * 0.035f, 0f, floatArrayOf(0.8f, 0.85f, 1f), m.alpha)
            val blink = if (sin(elapsed * 5f + m.phase) > 0f) 1f else 0.35f
            drawMesh(sphere, x, y + 1.08f * s, z, s * 0.09f, s * 0.09f, s * 0.09f, 0f, floatArrayOf(1f, 0.75f, 0.25f), m.alpha * blink)
        }

        private fun drawMesh(mesh: Mesh, x: Float, y: Float, z: Float, sx: Float, sy: Float, sz: Float, rotZ: Float, color: FloatArray, alpha: Float) {
            Matrix.setIdentityM(model, 0)
            Matrix.translateM(model, 0, x, y, z)
            // Модель всегда лицом к игроку: силуэт не теряется при обходе по углу.
            Matrix.rotateM(model, 0, -deltaAngle(0f, 0f), 0f, 1f, 0f)
            if (rotZ != 0f) Matrix.rotateM(model, 0, rotZ, 0f, 0f, 1f)
            Matrix.scaleM(model, 0, sx, sy, sz)
            Matrix.multiplyMM(mvp, 0, projection, 0, view, 0)
            Matrix.multiplyMM(temp, 0, mvp, 0, model, 0)
            GLES20.glUniformMatrix4fv(mvpHandle, 1, false, temp, 0)
            GLES20.glUniformMatrix4fv(modelHandle, 1, false, model, 0)
            GLES20.glUniform3f(colorHandle, color[0], color[1], color[2])
            GLES20.glUniform1f(alphaHandle, alpha.coerceIn(0f, 1f))
            mesh.buffer.position(0)
            GLES20.glEnableVertexAttribArray(positionHandle)
            GLES20.glVertexAttribPointer(positionHandle, 3, GLES20.GL_FLOAT, false, 24, mesh.buffer)
            mesh.buffer.position(3)
            GLES20.glEnableVertexAttribArray(normalHandle)
            GLES20.glVertexAttribPointer(normalHandle, 3, GLES20.GL_FLOAT, false, 24, mesh.buffer)
            GLES20.glDrawArrays(GLES20.GL_TRIANGLES, 0, mesh.vertexCount)
            GLES20.glDisableVertexAttribArray(positionHandle)
            GLES20.glDisableVertexAttribArray(normalHandle)
        }

        private fun buildProgram(): Int {
            val vertex = """
                attribute vec3 aPosition;
                attribute vec3 aNormal;
                uniform mat4 uMvp;
                uniform mat4 uModel;
                varying float vLight;
                varying vec3 vNormal;
                void main() {
                    vec3 n = normalize(mat3(uModel) * aNormal);
                    vec3 lightDir = normalize(vec3(0.35, 0.8, 0.65));
                    float rim = pow(1.0 - abs(n.z), 2.0);
                    vLight = 0.34 + 0.58 * max(dot(n, lightDir), 0.0) + rim * 0.38;
                    vNormal = n;
                    gl_Position = uMvp * vec4(aPosition, 1.0);
                }
            """.trimIndent()
            val fragment = """
                precision mediump float;
                uniform vec3 uColor;
                uniform float uAlpha;
                varying float vLight;
                void main() { gl_FragColor = vec4(uColor * vLight, uAlpha); }
            """.trimIndent()
            fun shader(type: Int, source: String): Int {
                val id = GLES20.glCreateShader(type)
                GLES20.glShaderSource(id, source)
                GLES20.glCompileShader(id)
                return id
            }
            val p = GLES20.glCreateProgram()
            GLES20.glAttachShader(p, shader(GLES20.GL_VERTEX_SHADER, vertex))
            GLES20.glAttachShader(p, shader(GLES20.GL_FRAGMENT_SHADER, fragment))
            GLES20.glLinkProgram(p)
            return p
        }

        private data class Mesh(val buffer: FloatBuffer, val vertexCount: Int)

        private fun meshFrom(data: List<Float>): Mesh {
            val arr = FloatArray(data.size) { data[it] }
            val buffer = ByteBuffer.allocateDirect(arr.size * 4).order(ByteOrder.nativeOrder()).asFloatBuffer()
            buffer.put(arr).position(0)
            return Mesh(buffer, arr.size / 6)
        }

        private fun createSphere(stacks: Int, slices: Int): Mesh {
            val data = mutableListOf<Float>()
            fun point(lat: Float, lon: Float): FloatArray {
                val x = cos(lat) * sin(lon)
                val y = sin(lat)
                val z = cos(lat) * cos(lon)
                return floatArrayOf(x, y, z, x, y, z)
            }
            for (i in 0 until stacks) {
                val lat1 = -PI.toFloat() / 2f + PI.toFloat() * i / stacks
                val lat2 = -PI.toFloat() / 2f + PI.toFloat() * (i + 1) / stacks
                for (j in 0 until slices) {
                    val lon1 = 2f * PI.toFloat() * j / slices
                    val lon2 = 2f * PI.toFloat() * (j + 1) / slices
                    val a = point(lat1, lon1); val b = point(lat2, lon1); val c = point(lat2, lon2); val d = point(lat1, lon2)
                    data.addAll(a.toList()); data.addAll(b.toList()); data.addAll(c.toList())
                    data.addAll(a.toList()); data.addAll(c.toList()); data.addAll(d.toList())
                }
            }
            return meshFrom(data)
        }

        private fun createCone(segments: Int): Mesh {
            val data = mutableListOf<Float>()
            fun add(p: FloatArray) { data.addAll(p.toList()) }
            for (i in 0 until segments) {
                val a1 = 2f * PI.toFloat() * i / segments
                val a2 = 2f * PI.toFloat() * (i + 1) / segments
                val base1 = floatArrayOf(sin(a1), -0.5f, cos(a1), sin(a1), 0.2f, cos(a1))
                val base2 = floatArrayOf(sin(a2), -0.5f, cos(a2), sin(a2), 0.2f, cos(a2))
                val tip = floatArrayOf(0f, 0.55f, 0f, 0f, 1f, 0f)
                add(base1); add(tip); add(base2)
                val center = floatArrayOf(0f, -0.5f, 0f, 0f, -1f, 0f)
                add(center); add(base2); add(base1)
            }
            return meshFrom(data)
        }

        private fun createBox(): Mesh {
            val v = arrayOf(
                floatArrayOf(-0.5f,-0.5f,0.5f), floatArrayOf(0.5f,-0.5f,0.5f), floatArrayOf(0.5f,0.5f,0.5f), floatArrayOf(-0.5f,0.5f,0.5f),
                floatArrayOf(-0.5f,-0.5f,-0.5f), floatArrayOf(0.5f,-0.5f,-0.5f), floatArrayOf(0.5f,0.5f,-0.5f), floatArrayOf(-0.5f,0.5f,-0.5f)
            )
            val faces = listOf(
                intArrayOf(0,1,2,0,2,3) to floatArrayOf(0f,0f,1f),
                intArrayOf(5,4,7,5,7,6) to floatArrayOf(0f,0f,-1f),
                intArrayOf(1,5,6,1,6,2) to floatArrayOf(1f,0f,0f),
                intArrayOf(4,0,3,4,3,7) to floatArrayOf(-1f,0f,0f),
                intArrayOf(3,2,6,3,6,7) to floatArrayOf(0f,1f,0f),
                intArrayOf(4,5,1,4,1,0) to floatArrayOf(0f,-1f,0f)
            )
            val data = mutableListOf<Float>()
            for ((indices, n) in faces) for (idx in indices) { data.addAll(v[idx].toList()); data.addAll(n.toList()) }
            return meshFrom(data)
        }

        private fun deltaAngle(a: Float, b: Float): Float {
            var d = a - b
            while (d > 180f) d -= 360f
            while (d < -180f) d += 360f
            return d
        }

        private fun lerp(a: Float, b: Float, t: Float): Float = a + (b - a) * t
    }
}
