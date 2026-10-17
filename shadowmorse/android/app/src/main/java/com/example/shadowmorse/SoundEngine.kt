package com.example.shadowmorse

import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioTrack
import java.util.concurrent.Executors
import kotlin.math.PI
import kotlin.math.exp
import kotlin.math.sin
import kotlin.math.tanh

/**
 * Синтезатор игровых звуков без аудиофайлов и без назойливого proximity-писка.
 * Каждый эффект — отдельная маленькая партитура: гармоники, шумовой слой, атака/затухание
 * и короткое эхо. Так вспышка, лазер, щит, Морзе, лечение и босс звучат по-разному,
 * а не одним квадратным «пиксельным» тоном.
 */
class SoundEngine {
    private val executor = Executors.newSingleThreadExecutor()
    @Volatile private var closed = false

    private data class Voice(
        val startSec: Float,
        val durationSec: Float,
        val startFreq: Float,
        val endFreq: Float,
        val volume: Float,
        val harmonics: FloatArray = floatArrayOf(1f, 0.35f, 0.12f),
        val noise: Float = 0f,
        val attackSec: Float = 0.008f
    )

    private fun play(vararg voices: Voice) {
        if (closed || voices.isEmpty()) return
        executor.execute {
            try { render(voices.toList()) } catch (_: Exception) { }
        }
    }

    /** Яркая вспышка: короткий световой «всплеск» вверх + мягкое шипение. */
    fun hitFlash() = play(
        Voice(0f, .16f, 740f, 1560f, .34f, floatArrayOf(1f, .45f, .18f)),
        Voice(0f, .11f, 2200f, 900f, .10f, floatArrayOf(1f), noise = .55f)
    )

    /** Лазерный разрез: нисходящий режущий свист и сухой треск. */
    fun hitLaser() = play(
        Voice(0f, .20f, 1750f, 260f, .34f, floatArrayOf(1f, .55f, .30f, .12f)),
        Voice(.015f, .09f, 3200f, 1800f, .12f, floatArrayOf(1f), noise = .75f)
    )

    fun shieldHit() = play(
        Voice(0f, .14f, 1180f, 820f, .30f, floatArrayOf(1f, .25f)),
        Voice(0f, .06f, 2400f, 1700f, .10f, floatArrayOf(1f), noise = .35f)
    )

    fun shieldBreak() = play(
        Voice(0f, .28f, 1500f, 190f, .38f, floatArrayOf(1f, .5f, .25f)),
        Voice(0f, .18f, 900f, 300f, .16f, floatArrayOf(1f), noise = .8f),
        Voice(.07f, .20f, 620f, 120f, .22f, floatArrayOf(1f, .35f))
    )

    fun shieldBlock() = play(
        Voice(0f, .22f, 310f, 190f, .42f, floatArrayOf(1f, .30f, .10f)),
        Voice(.02f, .16f, 1240f, 880f, .13f, floatArrayOf(1f, .2f))
    )

    fun runeBreak() = play(
        Voice(0f, .18f, 1560f, 1560f, .24f, floatArrayOf(1f, .4f, .2f)),
        Voice(.055f, .20f, 2090f, 2090f, .20f, floatArrayOf(1f, .35f)),
        Voice(.11f, .30f, 2630f, 1980f, .18f, floatArrayOf(1f, .3f), noise = .12f)
    )

    fun morseProgress() = play(Voice(0f, .10f, 880f, 880f, .26f, floatArrayOf(1f, .28f)))
    fun morseError() = play(
        Voice(0f, .13f, 220f, 185f, .30f, floatArrayOf(1f, .45f)),
        Voice(.10f, .16f, 185f, 150f, .28f, floatArrayOf(1f, .4f))
    )

    /** Смерть монстра: низкий провал, воздушный выдох и короткий магический отзвук. */
    fun death() = play(
        Voice(0f, .38f, 320f, 42f, .48f, floatArrayOf(1f, .48f, .22f)),
        Voice(0f, .24f, 700f, 130f, .15f, floatArrayOf(1f), noise = .65f),
        Voice(.05f, .28f, 1180f, 240f, .12f, floatArrayOf(1f, .3f))
    )

    /** Полученный урон: глухой удар и низкий тревожный провал, без резкого писка. */
    fun hurt() = play(
        Voice(0f, .34f, 118f, 48f, .62f, floatArrayOf(1f, .55f, .25f)),
        Voice(0f, .16f, 420f, 110f, .16f, floatArrayOf(1f), noise = .45f)
    )

    fun heal() = play(
        Voice(0f, .16f, 523f, 523f, .25f, floatArrayOf(1f, .3f)),
        Voice(.07f, .18f, 659f, 659f, .23f, floatArrayOf(1f, .3f)),
        Voice(.14f, .26f, 784f, 784f, .22f, floatArrayOf(1f, .28f))
    )

    fun upgrade() = play(
        Voice(0f, .14f, 440f, 440f, .23f, floatArrayOf(1f, .3f)),
        Voice(.06f, .15f, 554f, 554f, .22f, floatArrayOf(1f, .3f)),
        Voice(.12f, .16f, 659f, 659f, .22f, floatArrayOf(1f, .3f)),
        Voice(.18f, .28f, 880f, 880f, .22f, floatArrayOf(1f, .32f))
    )

    /** Появление босса: два низких удара и растущая тёмная волна. */
    fun boss() = play(
        Voice(0f, .48f, 58f, 44f, .62f, floatArrayOf(1f, .6f, .25f)),
        Voice(.20f, .55f, 73f, 52f, .55f, floatArrayOf(1f, .55f, .22f)),
        Voice(.12f, .70f, 146f, 220f, .20f, floatArrayOf(1f, .42f, .18f))
    )

    fun victory() = play(
        Voice(0f, .18f, 392f, 392f, .25f, floatArrayOf(1f, .3f)),
        Voice(.10f, .18f, 494f, 494f, .24f, floatArrayOf(1f, .3f)),
        Voice(.20f, .20f, 587f, 587f, .24f, floatArrayOf(1f, .3f)),
        Voice(.30f, .42f, 784f, 784f, .25f, floatArrayOf(1f, .34f))
    )

    fun defeat() = play(
        Voice(0f, .45f, 220f, 110f, .42f, floatArrayOf(1f, .5f, .2f)),
        Voice(.22f, .60f, 165f, 55f, .40f, floatArrayOf(1f, .48f, .18f))
    )

    /** Разные расходники — разные короткие музыкальные/шумовые жесты. */
    fun consumable(type: GameView.Consumable) {
        when (type) {
            GameView.Consumable.GRENADE -> play(
                Voice(0f, .34f, 180f, 38f, .58f, floatArrayOf(1f, .5f, .2f)),
                Voice(0f, .22f, 1000f, 160f, .22f, floatArrayOf(1f), noise = .9f),
                Voice(.04f, .30f, 1450f, 260f, .15f, floatArrayOf(1f, .3f))
            )
            GameView.Consumable.SHIELD -> shieldBlock()
            GameView.Consumable.SLOW -> play(
                Voice(0f, .55f, 880f, 220f, .30f, floatArrayOf(1f, .4f, .15f)),
                Voice(.10f, .45f, 660f, 180f, .18f, floatArrayOf(1f, .35f))
            )
            GameView.Consumable.RADAR -> play(
                Voice(0f, .22f, 1040f, 1040f, .27f, floatArrayOf(1f, .25f)),
                Voice(.20f, .30f, 1040f, 1040f, .18f, floatArrayOf(1f, .22f)),
                Voice(.42f, .38f, 1040f, 1040f, .11f, floatArrayOf(1f, .18f))
            )
            GameView.Consumable.LURE -> play(
                Voice(0f, .16f, 660f, 660f, .24f, floatArrayOf(1f, .3f)),
                Voice(.12f, .16f, 660f, 660f, .20f, floatArrayOf(1f, .3f)),
                Voice(.24f, .22f, 880f, 880f, .20f, floatArrayOf(1f, .3f))
            )
            GameView.Consumable.MEDKIT -> heal()
            GameView.Consumable.BOOSTER -> play(
                Voice(0f, .25f, 520f, 1320f, .30f, floatArrayOf(1f, .38f, .16f)),
                Voice(.08f, .18f, 1560f, 1980f, .12f, floatArrayOf(1f, .25f))
            )
            GameView.Consumable.HOLY -> play(
                Voice(0f, .28f, 1318f, 1318f, .20f, floatArrayOf(1f, .36f, .14f)),
                Voice(.07f, .34f, 1760f, 1560f, .18f, floatArrayOf(1f, .3f)),
                Voice(.14f, .40f, 2210f, 1760f, .13f, floatArrayOf(1f, .25f), noise = .10f)
            )
            GameView.Consumable.SALT -> play(
                Voice(0f, .24f, 2600f, 1400f, .13f, floatArrayOf(1f), noise = .85f),
                Voice(.05f, .28f, 1800f, 900f, .10f, floatArrayOf(1f), noise = .7f)
            )
        }
    }

    /** Совместимость для редких общих подтверждений; основной интерфейс использует конкретные эффекты выше. */
    fun power() = upgrade()

    private fun render(voices: List<Voice>) {
        val sampleRate = 44_100
        val totalSec = voices.maxOf { it.startSec + it.durationSec } + 0.14f
        val frames = (sampleRate * totalSec).toInt().coerceAtLeast(1)
        val mix = FloatArray(frames)
        var seed = 987654321

        fun noiseSample(): Float {
            seed = (seed * 1103515245 + 12345) and 0x7fffffff
            return (seed / Int.MAX_VALUE.toFloat()) * 2f - 1f
        }

        for (voice in voices) {
            val start = (voice.startSec * sampleRate).toInt()
            val count = (voice.durationSec * sampleRate).toInt()
            var phase = 0.0
            var lastNoise = 0f
            for (i in 0 until count) {
                val idx = start + i
                if (idx !in mix.indices) continue
                val t = i.toFloat() / count.coerceAtLeast(1)
                val freq = voice.startFreq + (voice.endFreq - voice.startFreq) * t
                phase += 2.0 * PI * freq / sampleRate
                var sample = 0.0
                voice.harmonics.forEachIndexed { h, amp ->
                    sample += sin(phase * (h + 1)) * amp
                }
                if (voice.noise > 0f) {
                    // Слегка сглаженный шум звучит как воздух/шипение, а не как цифровой треск.
                    lastNoise = lastNoise * 0.62f + noiseSample() * 0.38f
                    sample = sample * (1f - voice.noise) + lastNoise * voice.noise * 1.8f
                }
                val attack = minOf(1f, i / (voice.attackSec * sampleRate).coerceAtLeast(1f))
                val decay = exp(-3.2 * t).toFloat()
                mix[idx] += (sample * attack * decay * voice.volume).toFloat()
            }
        }

        // Короткое рассеянное эхо добавляет объём без внешних файлов и ревербератора.
        val echoDelay = (0.085f * sampleRate).toInt()
        for (i in frames - 1 downTo echoDelay) {
            mix[i] += mix[i - echoDelay] * 0.16f
        }

        val data = ShortArray(frames)
        for (i in mix.indices) {
            data[i] = (tanh(mix[i].toDouble() * 0.82) * Short.MAX_VALUE * 0.88).toInt().toShort()
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
            Thread.sleep((totalSec * 1000).toLong() + 30L)
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
