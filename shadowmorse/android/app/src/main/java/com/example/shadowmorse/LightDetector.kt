package com.example.shadowmorse

import android.media.Image
import kotlin.math.abs
import kotlin.math.hypot
import kotlin.math.max
import kotlin.math.min

/** Нормализованная точка в уже повёрнутом «вертикальном» кадре: 0..1 по ширине/высоте. */
data class FrameDetections(
    val flashActive: Boolean = false,
    val flashU: Float = 0f,
    val flashV: Float = 0f,
    val flashRadius: Float = 0f,
    val laserActive: Boolean = false,
    val laserU: Float = 0f,
    val laserV: Float = 0f,
    val laserPrevU: Float? = null,
    val laserPrevV: Float? = null,
    val laserGreen: Boolean = false,
    val laserTrackId: Long = 0L,
    val timestampMs: Long = 0L
)

/**
 * Детектор внешнего света по YUV-кадрам камеры.
 *
 * Улучшения относительно PWA:
 * - порог фонаря адаптивный: зависит от текущей средней яркости сцены;
 * - ищется крупнейшая связная яркая область, а не просто сумма всех светлых пикселей;
 * - лазер подтверждается во времени, сглаживается и имеет стабильный trackId одного ведения;
 * - анализ идёт на сетке не более 160x90, поэтому не нагружает память и CPU.
 */
class LightDetector {
    private var ambient = 70f
    private var lastLaser: Candidate? = null
    private var candidateStreak = 0
    private var activeTrackId = 0L
    private var nextTrackId = 1L
    private var lastLaserSeenMs = 0L

    private data class Candidate(val u: Float, val v: Float, val green: Boolean, val area: Int)

    fun process(image: Image, rotationDegrees: Int): FrameDetections {
        val now = System.currentTimeMillis()
        val width = image.width
        val height = image.height
        if (width <= 0 || height <= 0 || image.planes.size < 3) return FrameDetections(timestampMs = now)

        val stepX = max(1, width / 160)
        val stepY = max(1, height / 90)
        val gw = (width + stepX - 1) / stepX
        val gh = (height + stepY - 1) / stepY
        val brightMask = BooleanArray(gw * gh)
        val laserMask = ByteArray(gw * gh) // 1 red, 2 green

        val yPlane = image.planes[0]
        val uPlane = image.planes[1]
        val vPlane = image.planes[2]
        val yBuffer = yPlane.buffer
        val uBuffer = uPlane.buffer
        val vBuffer = vPlane.buffer

        var brightnessSum = 0L
        var samples = 0
        var gy = 0
        var y = 0
        while (y < height) {
            var gx = 0
            var x = 0
            while (x < width) {
                val yi = y * yPlane.rowStride + x * yPlane.pixelStride
                if (yi >= 0 && yi < yBuffer.limit()) {
                    val yv = yBuffer.get(yi).toInt() and 0xFF
                    brightnessSum += yv
                    samples++

                    val uvX = x / 2
                    val uvY = y / 2
                    val ui = uvY * uPlane.rowStride + uvX * uPlane.pixelStride
                    val vi = uvY * vPlane.rowStride + uvX * vPlane.pixelStride
                    if (ui >= 0 && ui < uBuffer.limit() && vi >= 0 && vi < vBuffer.limit()) {
                        val uv = (uBuffer.get(ui).toInt() and 0xFF) - 128
                        val vv = (vBuffer.get(vi).toInt() and 0xFF) - 128
                        val r = (yv + 1.402f * vv).toInt().coerceIn(0, 255)
                        val g = (yv - 0.344136f * uv - 0.714136f * vv).toInt().coerceIn(0, 255)
                        val b = (yv + 1.772f * uv).toInt().coerceIn(0, 255)
                        val mx = max(r, max(g, b))
                        val mn = min(r, min(g, b))
                        val saturation = mx - mn
                        val idx = gy * gw + gx

                        val flashThreshold = max(205f, min(242f, ambient + 82f))
                        val neutralBright = yv > flashThreshold && saturation < 118
                        if (neutralBright) brightMask[idx] = true

                        val redLaser = r > 205 && saturation > 100 && r > g * 1.70f && r > b * 1.70f && g < 180 && b < 180
                        val greenLaser = g > 205 && saturation > 100 && g > r * 1.52f && g > b * 1.52f && r < 195 && b < 195
                        if (redLaser) laserMask[idx] = 1 else if (greenLaser) laserMask[idx] = 2
                    }
                }
                x += stepX
                gx++
            }
            y += stepY
            gy++
        }

        if (samples > 0) {
            val mean = brightnessSum.toFloat() / samples
            // Медленная адаптация только к общей сцене; резкая вспышка не должна мгновенно поднять порог.
            ambient += (mean - ambient) * 0.035f
        }

        val flash = largestComponent(brightMask, gw, gh, minArea = 10)
        val flashDetection = if (flash != null) {
            val (u, v) = upright(flash.first, flash.second, rotationDegrees)
            Triple(u, v, flash.third)
        } else null

        val laserCandidate = bestLaserComponent(laserMask, gw, gh)?.let { c ->
            val (u, v) = upright(c.u, c.v, rotationDegrees)
            Candidate(u, v, c.green, c.area)
        }

        var laserActive = false
        var laserU = 0f
        var laserV = 0f
        var laserPrevU: Float? = null
        var laserPrevV: Float? = null
        var laserGreen = false

        if (laserCandidate != null) {
            val previous = lastLaser
            if (previous != null && previous.green == laserCandidate.green) {
                val jump = hypot((laserCandidate.u - previous.u).toDouble(), (laserCandidate.v - previous.v).toDouble())
                candidateStreak = if (jump < 0.22 || candidateStreak >= 2) candidateStreak + 1 else 1
            } else candidateStreak = 1

            if (candidateStreak >= 2) {
                if (activeTrackId == 0L || now - lastLaserSeenMs > 180L) activeTrackId = nextTrackId++
                laserPrevU = previous?.u
                laserPrevV = previous?.v
                laserU = if (previous != null && candidateStreak > 2) previous.u + (laserCandidate.u - previous.u) * 0.68f else laserCandidate.u
                laserV = if (previous != null && candidateStreak > 2) previous.v + (laserCandidate.v - previous.v) * 0.68f else laserCandidate.v
                laserGreen = laserCandidate.green
                laserActive = true
                lastLaserSeenMs = now
            }
            lastLaser = Candidate(laserU.takeIf { laserActive } ?: laserCandidate.u, laserV.takeIf { laserActive } ?: laserCandidate.v, laserCandidate.green, laserCandidate.area)
        } else {
            candidateStreak = 0
            lastLaser = null
            if (now - lastLaserSeenMs > 180L) activeTrackId = 0L
        }

        return FrameDetections(
            flashActive = flashDetection != null,
            flashU = flashDetection?.first ?: 0f,
            flashV = flashDetection?.second ?: 0f,
            flashRadius = if (flashDetection != null) (kotlin.math.sqrt(flashDetection.third.toDouble()).toFloat() / 90f).coerceIn(0.05f, 0.22f) else 0f,
            laserActive = laserActive,
            laserU = laserU,
            laserV = laserV,
            laserPrevU = laserPrevU,
            laserPrevV = laserPrevV,
            laserGreen = laserGreen,
            laserTrackId = activeTrackId,
            timestampMs = now
        )
    }

    private fun upright(nx: Float, ny: Float, rotationDegrees: Int): Pair<Float, Float> = when ((rotationDegrees % 360 + 360) % 360) {
        90 -> (1f - ny) to nx
        180 -> (1f - nx) to (1f - ny)
        270 -> ny to (1f - nx)
        else -> nx to ny
    }

    /** Крупнейшая связная область маски. Возвращает центр в нормализованных координатах исходного кадра и площадь. */
    private fun largestComponent(mask: BooleanArray, gw: Int, gh: Int, minArea: Int): Triple<Float, Float, Int>? {
        val visited = BooleanArray(mask.size)
        val stack = IntArray(mask.size)
        var best: Triple<Float, Float, Int>? = null
        for (start in mask.indices) {
            if (!mask[start] || visited[start]) continue
            var top = 0
            var area = 0
            var sx = 0L
            var sy = 0L
            stack[top++] = start
            visited[start] = true
            while (top > 0) {
                val cur = stack[--top]
                val cx = cur % gw
                val cy = cur / gw
                area++; sx += cx; sy += cy
                if (cx > 0 && mask[cur - 1] && !visited[cur - 1]) { visited[cur - 1] = true; stack[top++] = cur - 1 }
                if (cx + 1 < gw && mask[cur + 1] && !visited[cur + 1]) { visited[cur + 1] = true; stack[top++] = cur + 1 }
                if (cy > 0 && mask[cur - gw] && !visited[cur - gw]) { visited[cur - gw] = true; stack[top++] = cur - gw }
                if (cy + 1 < gh && mask[cur + gw] && !visited[cur + gw]) { visited[cur + gw] = true; stack[top++] = cur + gw }
            }
            if (area >= minArea && (best == null || area > best!!.third)) {
                best = Triple((sx.toFloat() / area) / gw.coerceAtLeast(1), (sy.toFloat() / area) / gh.coerceAtLeast(1), area)
            }
        }
        return best
    }

    private fun bestLaserComponent(mask: ByteArray, gw: Int, gh: Int): Candidate? {
        val visited = BooleanArray(mask.size)
        val stack = IntArray(mask.size)
        var best: Candidate? = null
        var bestScore = -1f
        for (start in mask.indices) {
            val kind = mask[start]
            if (kind == 0.toByte() || visited[start]) continue
            var top = 0
            var area = 0
            var sx = 0L
            var sy = 0L
            var minX = gw; var minY = gh; var maxX = -1; var maxY = -1
            stack[top++] = start
            visited[start] = true
            while (top > 0) {
                val cur = stack[--top]
                val cx = cur % gw
                val cy = cur / gw
                area++; sx += cx; sy += cy
                minX = min(minX, cx); minY = min(minY, cy); maxX = max(maxX, cx); maxY = max(maxY, cy)
                if (cx > 0 && mask[cur - 1] == kind && !visited[cur - 1]) { visited[cur - 1] = true; stack[top++] = cur - 1 }
                if (cx + 1 < gw && mask[cur + 1] == kind && !visited[cur + 1]) { visited[cur + 1] = true; stack[top++] = cur + 1 }
                if (cy > 0 && mask[cur - gw] == kind && !visited[cur - gw]) { visited[cur - gw] = true; stack[top++] = cur - gw }
                if (cy + 1 < gh && mask[cur + gw] == kind && !visited[cur + gw]) { visited[cur + gw] = true; stack[top++] = cur + gw }
            }
            val bw = maxX - minX + 1
            val bh = maxY - minY + 1
            if (area in 1..55 && bw <= 9 && bh <= 9) {
                val compactness = area.toFloat() / max(1, bw * bh).toFloat()
                val score = compactness * 100f + area
                if (score > bestScore) {
                    bestScore = score
                    best = Candidate((sx.toFloat() / area) / gw.coerceAtLeast(1), (sy.toFloat() / area) / gh.coerceAtLeast(1), kind == 2.toByte(), area)
                }
            }
        }
        return best
    }
}
