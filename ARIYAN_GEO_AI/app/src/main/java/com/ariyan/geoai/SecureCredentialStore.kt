package com.ariyan.geoai

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/**
 * SecureCredentialStore -- on-device encrypted storage for the user's own
 * OpenTopography API key and Copernicus Data Space Ecosystem OAuth
 * client ID/secret.
 *
 * ADDED THIS SESSION as part of the real-data-first redesign (see
 * MainActivity.kt's own class doc comment for the full picture).
 * Previously these were held only in memory for the current app session,
 * which meant real data was effectively opt-in PER SESSION -- the user
 * had to retype credentials, and remember to, every single time they
 * opened the app. That made the ACTUAL default experience the
 * synthetic-data path, directly contradicting this project's hard
 * requirement that nothing should be synthetic/fake. Persisting
 * credentials here is what makes "real data always attempted
 * automatically, no manual toggle" practically usable rather than just
 * theoretically correct.
 *
 * Uses androidx.security.crypto.EncryptedSharedPreferences (AES256_SIV
 * key encryption, AES256_GCM value encryption, backed by a MasterKey
 * held in the Android Keystore) -- this exact API shape (MasterKey.
 * Builder + EncryptedSharedPreferences.create with the two
 * PrefKeyEncryptionScheme/PrefValueEncryptionScheme arguments) was
 * confirmed against Android's current official Security reference docs
 * before writing this, matching this project's established practice of
 * verifying Android API shapes against live docs before committing
 * (already done once for the AuthorizationClient/Drive-consent shape in
 * OfflineDataActivity.kt).
 *
 * HONEST NOTE ON DEPRECATION: EncryptedSharedPreferences was marked
 * @deprecated as of security-crypto 1.1.0 (Google's stated long-term
 * direction is Jetpack DataStore + Tink instead), but the class itself
 * is still present, shipped, and functional in this current stable 1.1.0
 * release -- see build.gradle.kts's own comment on the security-crypto
 * dependency for why a full DataStore+Tink migration was deliberately
 * not taken on in this pass (materially bigger, riskier change than this
 * session's actual goal). Revisit if a future AndroidX release ever
 * actually removes the class, not preemptively.
 *
 * HONEST STATE: this class is straightforward, well-documented AndroidX
 * API usage, but has NOT yet been run on an actual device to confirm a
 * value written here in one app session is correctly read back
 * (decrypted) in a later one -- that on-device confirmation is the
 * honest next step once this build compiles clean, same practice as
 * every other real piece of this project.
 */
class SecureCredentialStore(context: Context) {

    private val prefs: SharedPreferences = run {
        val masterKey = MasterKey.Builder(context)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        EncryptedSharedPreferences.create(
            context,
            PREFS_FILE_NAME,
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        )
    }

    var openTopographyApiKey: String
        get() = prefs.getString(KEY_OPENTOPOGRAPHY_API_KEY, "") ?: ""
        set(value) = prefs.edit().putString(KEY_OPENTOPOGRAPHY_API_KEY, value).apply()

    var demType: String
        get() = prefs.getString(KEY_DEM_TYPE, "") ?: ""
        set(value) = prefs.edit().putString(KEY_DEM_TYPE, value).apply()

    var copernicusClientId: String
        get() = prefs.getString(KEY_COPERNICUS_CLIENT_ID, "") ?: ""
        set(value) = prefs.edit().putString(KEY_COPERNICUS_CLIENT_ID, value).apply()

    var copernicusClientSecret: String
        get() = prefs.getString(KEY_COPERNICUS_CLIENT_SECRET, "") ?: ""
        set(value) = prefs.edit().putString(KEY_COPERNICUS_CLIENT_SECRET, value).apply()

    companion object {
        private const val PREFS_FILE_NAME = "ariyan_secure_credentials"
        private const val KEY_OPENTOPOGRAPHY_API_KEY = "opentopography_api_key"
        private const val KEY_DEM_TYPE = "dem_type"
        private const val KEY_COPERNICUS_CLIENT_ID = "copernicus_client_id"
        private const val KEY_COPERNICUS_CLIENT_SECRET = "copernicus_client_secret"
    }
}
