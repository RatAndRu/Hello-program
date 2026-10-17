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
        val spec = PBEKeySpec(pin.toCharArray(), salt, 120_000, 256)
        val bytes = SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256").generateSecret(spec).encoded
        return SecretKeySpec(bytes, "AES")
    }

    private fun masterKey(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getEntry(MASTER_ALIAS, null) as? KeyStore.SecretKeyEntry)?.let { return it.secretKey }
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

    private fun pack(iv: ByteArray, bytes: ByteArray): String =
        Base64.encodeToString(iv + bytes, Base64.NO_WRAP)

    private fun unpack(value: String): Pair<ByteArray, ByteArray> {
        val all = Base64.decode(value, Base64.DEFAULT)
        return all.copyOfRange(0, 12) to all.copyOfRange(12, all.size)
    }
}
