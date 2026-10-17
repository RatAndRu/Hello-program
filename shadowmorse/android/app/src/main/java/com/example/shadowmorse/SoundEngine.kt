package com.example.shadowmorse

import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioTrack
import java.util.concurrent.Executors
import kotlin.math.PI
import kotlin.math.sin

/** Полностью синтезируемые звуки без аудиофайлов: тоны, свипы и короткий шум на AudioTrack. */
class SoundEngine {
    private val executor = Executors.newSingleThreadExecutor()
    @Volatile private var closed = false

    fun tone(startFreq: Float, endFreq: Float, durationMs: Int, volume: Float = 0.5f, noise: Boolean = false) {
        if (closed) return
        executor.execute {
            try { playInternal(startFreq, endFreq, durationMs, volume.coerceIn(0.02f, 1f), noise) } catch (_: Exception) { }
        }
    }

    fun hitFlash() = tone(820f, 240f, 85, 0.45f)
    fun hitLaser() = tone(1350f, 320f, 95, 0.42f)
    fun death() { tone(260f, 45f, 260, 0.65f); tone(1200f, 180f, 160, 0.25f, noise = true) }
    fun hurt() = tone(95f, 55f, 340, 0.85f)
    fun power() = tone(520f, 980f, 150, 0.5f)
    fun boss() = tone(70f, 180f, 520, 0.8f)
    fun proximity(dist: Float) {
        val closeness = (1f - dist).coerceIn(0f, 1f)
        tone(420f + closeness * 720f, 360f + closeness * 620f, 70, 0.12f + closeness * 0.38f)
    }

    private fun playInternal(startFreq: Float, endFreq: Float, durationMs: Int, volume: Float, noise: Boolean) {
        val sampleRate = 22050
        val frames = (sampleRate * durationMs / 1000).coerceAtLeast(1)
        val data = ShortArray(frames)
        var phase = 0.0
        var seed = 22222
        for (i in 0 until frames) {
            val t = i.toDouble() / frames
            val freq = startFreq + (endFreq - startFreq) * t
            phase += 2.0 * PI * freq / sampleRate
            val envelope = sin(PI * t).coerceAtLeast(0.0)
            val sample = if (noise) {
                seed = (seed * 1103515245 + 12345) and 0x7fffffff
                ((seed / Int.MAX_VALUE.toFloat()) * 2f - 1f).toDouble()
            } else sin(phase)
            data[i] = (sample * envelope * volume * Short.MAX_VALUE).toInt().toShort()
        }
        val track = AudioTrack.Builder()
            .setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_GAME).setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build())
            .setAudioFormat(AudioFormat.Builder().setEncoding(AudioFormat.ENCODING_PCM_16BIT).setSampleRate(sampleRate).setChannelMask(AudioFormat.CHANNEL_OUT_MONO).build())
            .setBufferSizeInBytes(data.size * 2)
            .setTransferMode(AudioTrack.MODE_STATIC)
            .build()
        try {
            track.write(data, 0, data.size)
            track.play()
            Thread.sleep(durationMs.toLong() + 30L)
        } finally {
            try { track.stop() } catch (_: Exception) { }
            track.release()
        }
    }

    fun release() {
        closed = true
        executor.shutdown()
    }
}
