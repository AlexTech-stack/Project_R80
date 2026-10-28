package de.r80.companion

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.security.KeyStore
import java.util.Base64
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * The user's LLM API key, encrypted with a key of the Android Keystore that never leaves it
 * (AES-GCM). Only the encrypted form is in the app's preferences, and the app has no backup
 * (allowBackup false; it could not be decrypted on another phone anyway).
 */
object Secret {
    private const val ALIAS = "r80-llm-key"
    private const val PREF = "llm_key"

    private fun key(): SecretKey {
        val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (ks.getKey(ALIAS, null) as? SecretKey)?.let { return it }
        val gen = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        gen.init(KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .build())
        return gen.generateKey()
    }

    private fun prefs(ctx: Context) = ctx.getSharedPreferences("r80_secret", Context.MODE_PRIVATE)

    /** Stores the key; blank: removes it. */
    fun save(ctx: Context, value: String) {
        val v = value.trim()
        if (v.isEmpty()) {
            prefs(ctx).edit().remove(PREF).apply()
            return
        }
        val c = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key()) }
        val b64 = Base64.getEncoder()
        val ct = c.doFinal(v.toByteArray(Charsets.UTF_8))
        prefs(ctx).edit().putString(PREF, b64.encodeToString(c.iv) + ":" + b64.encodeToString(ct)).apply()
    }

    /** Whether a key is stored (without decrypting it). */
    fun has(ctx: Context): Boolean = prefs(ctx).contains(PREF)

    /** The key, or "" (none, or it cannot be decrypted any more). */
    fun load(ctx: Context): String {
        val s = prefs(ctx).getString(PREF, null) ?: return ""
        return try {
            val (iv, ct) = s.split(':').map { Base64.getDecoder().decode(it) }
            val c = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, iv)) }
            String(c.doFinal(ct), Charsets.UTF_8)
        } catch (_: Exception) {
            ""
        }
    }
}
