package com.example.pinphotoswidget

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.io.ByteArrayOutputStream
import java.security.KeyStore
import java.security.SecureRandom
import javax.crypto.Cipher
import javax.crypto.SecretKey
import javax.crypto.SecretKeyFactory
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.PBEKeySpec
import javax.crypto.spec.SecretKeySpec

/**
 * Настоящее шифрование файлов закрытых альбомов.
 *
 * Для каждого закрытого альбома создаётся отдельный случайный AES-256 ключ (DEK).
 * Фото шифруется этим ключом AES-GCM. Сам DEK в открытом виде на диск не пишется:
 * он хранится завёрнутым (wrapped) двумя способами — ключом Android Keystore
 * (неизвлекаемый, аппаратно защищённый там, где устройство это умеет) и ключом,
 * выведенным из PIN через PBKDF2. PIN нужен как обязательный способ закрытия,
 * а отпечаток открывает сессию в приложении после системной аутентификации.
 */
object VaultCrypto {
    private const val MASTER_ALIAS = "pinphotos_master_v1"
    private const val TRANSFORMATION = "AES/GCM/NoPadding"
    private const val MAGIC = "PFENC1"
    private val random = SecureRandom()

    fun newAlbumKey(): ByteArray = ByteArray(32).also { random.nextBytes(it) }

    fun wrapWithMaster(key: ByteArray): String {
        val iv = ByteArray(12).also { random.nextBytes(it) }
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, masterKey(), GCMParameterSpec(128, iv))
        return pack(iv, cipher.doFinal(key))
    }

    fun unwrapWithMaster(wrapped: String): ByteArray? = try {
        val (iv, bytes) = unpack(wrapped)
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.DECRYPT_MODE, masterKey(), GCMParameterSpec(128, iv))
        cipher.doFinal(bytes)
    } catch (e: Exception) { null }

    fun wrapWithPin(key: ByteArray, pin: String, saltB64: String): String {
        val iv = ByteArray(12).also { random.nextBytes(it) }
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, pinKey(pin, saltB64), GCMParameterSpec(128, iv))
        return pack(iv, cipher.doFinal(key))
    }

    fun unwrapWithPin(wrapped: String, pin: String, saltB64: String): ByteArray? = try {
        val (iv, bytes) = unpack(wrapped)
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.DECRYPT_MODE, pinKey(pin, saltB64), GCMParameterSpec(128, iv))
        cipher.doFinal(bytes)
    } catch (e: Exception) { null }

    fun encrypt(key: ByteArray, plain: ByteArray): ByteArray {
        val iv = ByteArray(12).also { random.nextBytes(it) }
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, SecretKeySpec(key, "AES"), GCMParameterSpec(128, iv))
        val body = cipher.doFinal(plain)
        val out = ByteArrayOutputStream()
        out.write(MAGIC.toByteArray(Charsets.US_ASCII)); out.write(iv); out.write(body)
        return out.toByteArray()
    }

    fun decrypt(key: ByteArray, stored: ByteArray): ByteArray? {
        if (stored.size < MAGIC.length + 12 + 1) return null
        val magic = stored.copyOfRange(0, MAGIC.length).toString(Charsets.US_ASCII)
        if (magic != MAGIC) return null
        val iv = stored.copyOfRange(MAGIC.length, MAGIC.length + 12)
        val body = stored.copyOfRange(MAGIC.length + 12, stored.size)
        return try {
            val cipher = Cipher.getInstance(TRANSFORMATION)
            cipher.init(Cipher.DECRYPT_MODE, SecretKeySpec(key, "AES"), GCMParameterSpec(128, iv))
            cipher.doFinal(body)
        } catch (e: Exception) { null }
    }

    fun isEncrypted(stored: ByteArray): Boolean =
        stored.size >= MAGIC.length && stored.copyOfRange(0, MAGIC.length).toString(Charsets.US_ASCII) == MAGIC

    private fun pinKey(pin: String, saltB64: String): SecretKey {
        val salt = Base64.decode(saltB64, Base64.DEFAULT)
        // PBKDF2WithHmacSHA256 есть на Android 8+, но на отдельных прошивках фабрика может
        // отсутствовать/падать. Тогда не роняем приложение, а используем совместимый PBKDF2.
        val algorithms = listOf("PBKDF2WithHmacSHA256" to 120_000, "PBKDF2WithHmacSHA1" to 120_000)
        var lastError: Exception? = null
        for ((algorithm, iterations) in algorithms) {
            try {
                val spec = PBEKeySpec(pin.toCharArray(), salt, iterations, 256)
                val bytes = SecretKeyFactory.getInstance(algorithm).generateSecret(spec).encoded
                if (bytes != null && bytes.isNotEmpty()) return SecretKeySpec(bytes, "AES")
            } catch (e: Exception) { lastError = e }
        }
        throw IllegalStateException("Устройство не поддерживает вывод ключа из PIN", lastError)
    }

    private fun masterKey(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        try {
            (store.getKey(MASTER_ALIAS, null) as? SecretKey)?.let { return it }
        } catch (e: Exception) {
            // Повреждённый/недействительный ключ нельзя использовать. Удаляем только запись
            // Keystore и создаём заново; файлы при этом защищает второй wrap из PIN.
            try { store.deleteEntry(MASTER_ALIAS) } catch (ignored: Exception) { }
        }
        fun generate(): SecretKey {
            val generator = javax.crypto.KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
            generator.init(
                KeyGenParameterSpec.Builder(MASTER_ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .setKeySize(256)
                    .build()
            )
            return generator.generateKey()
        }
        return try { generate() } catch (first: Exception) {
            try { store.deleteEntry(MASTER_ALIAS) } catch (ignored: Exception) { }
            try { generate() } catch (second: Exception) {
                throw IllegalStateException("Android Keystore недоступен для шифрования альбома", second)
            }
        }
    }

    /** Быстрая проверка, что ключ реально шифрует и расшифровывает на этом устройстве. */
    fun selfTest(key: ByteArray): Boolean {
        val sample = "pinphotos-key-test".toByteArray(Charsets.UTF_8)
        val decrypted = decrypt(key, encrypt(key, sample))
        return decrypted?.contentEquals(sample) == true
    }

    private fun pack(iv: ByteArray, bytes: ByteArray): String =
        Base64.encodeToString(iv + bytes, Base64.NO_WRAP)

    private fun unpack(value: String): Pair<ByteArray, ByteArray> {
        val all = Base64.decode(value, Base64.DEFAULT)
        return all.copyOfRange(0, 12) to all.copyOfRange(12, all.size)
    }
}
