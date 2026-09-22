package com.ariyan.geoai

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import org.json.JSONArray
import org.json.JSONObject

/**
 * The status of one stored credential slot, as last determined by an
 * actual test call (see the not-yet-built CredentialTester /
 * credentials_manager.py) -- never inferred, never assumed. UNTESTED is
 * the honest default for a freshly entered/imported slot: this project
 * does not claim a credential works until it has actually been checked
 * against the real service.
 */
enum class CredentialStatus {
    UNTESTED, VALID, INVALID
}

/**
 * One stored credential -- either a single OpenTopography API key
 * (secondaryValue left blank) or a Copernicus client_id/client_secret
 * pair (both populated). lastError, when present, is a short,
 * human-readable reason meant for on-screen display -- this project has
 * no logcat access on-device (see HANDOFF.md), so this string IS the
 * debugging trail for a failed slot, not a log line nobody will ever see.
 */
data class CredentialSlot(
    val id: String,
    val primaryValue: String,
    val secondaryValue: String = "",
    val status: CredentialStatus = CredentialStatus.UNTESTED,
    val lastError: String? = null,
    val lastTestedAtMillis: Long? = null
) {
    fun toJson(): JSONObject = JSONObject().apply {
        put("id", id)
        put("primary", primaryValue)
        put("secondary", secondaryValue)
        put("status", status.name)
        put("last_error", lastError ?: JSONObject.NULL)
        put("last_tested_at", lastTestedAtMillis ?: JSONObject.NULL)
    }

    companion object {
        fun fromJson(obj: JSONObject): CredentialSlot = CredentialSlot(
            id = obj.optString("id"),
            primaryValue = obj.optString("primary"),
            secondaryValue = obj.optString("secondary", ""),
            status = runCatching { CredentialStatus.valueOf(obj.optString("status")) }
                .getOrDefault(CredentialStatus.UNTESTED),
            lastError = if (obj.isNull("last_error")) null else obj.optString("last_error"),
            lastTestedAtMillis = if (obj.isNull("last_tested_at")) null else obj.optLong("last_tested_at")
        )
    }
}

/**
 * SecureCredentialStore -- on-device encrypted storage for the user's
 * OpenTopography API key(s) and Copernicus OAuth client credential
 * pair(s).
 *
 * REDESIGNED THIS SESSION from a single-value-per-service store into a
 * multi-slot backup/resilience store: each service can hold several
 * independently stored, independently tested credentials, so one
 * revoked/expired credential doesn't strand the user -- see this
 * session's roadmap discussion for the full reasoning. Explicitly NOT a
 * quota-pooling mechanism: OpenTopography's own terms are one-user-
 * one-key, and Copernicus quota is allocated per account regardless of
 * how many client_id/secret pairs exist under it, so multiple slots only
 * ever provide redundancy, never more total daily budget. A slot that
 * fails with an auth-type error (INVALID) auto-advances the active slot;
 * a slot that fails on a quota/rate-limit error should be recorded as
 * VALID (the credential itself is fine) with lastError set, and must
 * NOT trigger auto-advance -- see recordOpenTopographyResult /
 * recordCopernicusResult below.
 *
 * ONE-TIME MIGRATION: the previous version of this class stored a
 * single flat value per service under the three LEGACY_KEY_* names
 * below. Those keys are still read once, here, on construction -- if a
 * real value is found there and the new slot-list key is still empty,
 * it is migrated into a single new slot (UNTESTED -- it was never
 * actually verified under this new testing mechanism) automatically.
 * This exists so an existing user's already-entered real credentials
 * are never silently orphaned by this change. The old flat keys are
 * left in place afterward, untouched.
 *
 * Encryption approach (AES256_GCM master key, AES256_SIV key /
 * AES256_GCM value encryption via EncryptedSharedPreferences) is
 * unchanged from the previous version of this file -- see that
 * version's own doc comment for the deprecation note this still carries
 * forward honestly (security-crypto 1.1.0 marks
 * EncryptedSharedPreferences @deprecated in favor of a future
 * DataStore+Tink migration, not yet taken on).
 *
 * HONEST STATE: this class only stores results -- it does not itself
 * perform any test call. recordOpenTopographyResult/
 * recordCopernicusResult are the write side of that future flow;
 * nothing calls them yet (the actual HTTP test logic -- reusing
 * get_access_token for Copernicus, a minimal real DEM request for
 * OpenTopography -- is the next piece, not built in this pass). Like
 * the previous version of this file, this has also not yet been run on
 * an actual device to confirm the migration path and the new JSON
 * round-trip both work correctly on real, persisted, encrypted storage.
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

    init {
        migrateLegacyValuesIfNeeded()
    }

    // ---- DEM dataset type: unchanged, a single plain preference, never
    // a credential and never multi-slot. ----

    var demType: String
        get() = prefs.getString(KEY_DEM_TYPE, "") ?: ""
        set(value) = prefs.edit().putString(KEY_DEM_TYPE, value).apply()

    // ---- OpenTopography slots ----

    fun getOpenTopographySlots(): List<CredentialSlot> = readSlots(KEY_OPENTOPO_SLOTS)

    fun setOpenTopographySlots(slots: List<CredentialSlot>) = writeSlots(KEY_OPENTOPO_SLOTS, slots)

    var activeOpenTopographySlotId: String?
        get() = prefs.getString(KEY_OPENTOPO_ACTIVE_ID, null)
        set(value) = prefs.edit().putString(KEY_OPENTOPO_ACTIVE_ID, value).apply()

    /** The API key MainActivity / dem_source_mobile.py should actually
     * use right now: the active slot's value if one is set and still
     * exists, else the first slot in the list, else "" (no key
     * configured -- the existing, already-supported "offline only"
     * case). This is the single call site meant to replace every read
     * of the old flat `openTopographyApiKey` property. */
    fun activeOpenTopographyApiKey(): String =
        resolveActiveSlot(getOpenTopographySlots(), activeOpenTopographySlotId)?.primaryValue ?: ""

    /** Inserts or updates a single slot by id, leaving every other slot
     * in the list untouched -- used by MainActivity's own single-field
     * "Run Investigation" form so saving from there can never silently
     * wipe out backup slots added later from a dedicated credentials
     * management screen. Resets status to UNTESTED and clears any prior
     * error when the value actually changes, since carrying forward a
     * stale VALID/INVALID verdict for a value that just changed would
     * be dishonest. Does not touch which slot is marked active unless
     * none was set yet. */
    fun upsertOpenTopographySlot(id: String, primaryValue: String) {
        val existing = getOpenTopographySlots()
        val updated = if (existing.any { it.id == id }) {
            existing.map {
                if (it.id == id) it.copy(primaryValue = primaryValue, status = CredentialStatus.UNTESTED, lastError = null)
                else it
            }
        } else {
            existing + CredentialSlot(id = id, primaryValue = primaryValue)
        }
        setOpenTopographySlots(updated)
        if (activeOpenTopographySlotId == null) activeOpenTopographySlotId = id
    }

    // ---- Copernicus slots ----

    fun getCopernicusSlots(): List<CredentialSlot> = readSlots(KEY_COPERNICUS_SLOTS)

    fun setCopernicusSlots(slots: List<CredentialSlot>) = writeSlots(KEY_COPERNICUS_SLOTS, slots)

    var activeCopernicusSlotId: String?
        get() = prefs.getString(KEY_COPERNICUS_ACTIVE_ID, null)
        set(value) = prefs.edit().putString(KEY_COPERNICUS_ACTIVE_ID, value).apply()

    fun activeCopernicusClientId(): String =
        resolveActiveSlot(getCopernicusSlots(), activeCopernicusSlotId)?.primaryValue ?: ""

    fun activeCopernicusClientSecret(): String =
        resolveActiveSlot(getCopernicusSlots(), activeCopernicusSlotId)?.secondaryValue ?: ""

    /** Mirrors upsertOpenTopographySlot() exactly, for the client_id/
     * client_secret pair. */
    fun upsertCopernicusSlot(id: String, primaryValue: String, secondaryValue: String) {
        val existing = getCopernicusSlots()
        val updated = if (existing.any { it.id == id }) {
            existing.map {
                if (it.id == id) it.copy(
                    primaryValue = primaryValue, secondaryValue = secondaryValue,
                    status = CredentialStatus.UNTESTED, lastError = null
                ) else it
            }
        } else {
            existing + CredentialSlot(id = id, primaryValue = primaryValue, secondaryValue = secondaryValue)
        }
        setCopernicusSlots(updated)
        if (activeCopernicusSlotId == null) activeCopernicusSlotId = id
    }

    /** Records the outcome of an actual test call against one
     * OpenTopography slot and, on an auth-type failure (INVALID) of the
     * currently active slot, auto-advances activeOpenTopographySlotId to
     * the next non-INVALID slot if one exists -- the resilience behavior
     * this whole redesign is for. Callers handling a quota/rate-limit
     * failure should pass VALID (not INVALID) with lastError describing
     * it, so this auto-advance branch is never triggered by a quota
     * exhaustion -- switching OpenTopography slots on a 429 would just
     * be spreading volume across personal keys again, the thing this
     * design deliberately avoids. */
    fun recordOpenTopographyResult(slotId: String, status: CredentialStatus, lastError: String?) {
        recordResult(
            slots = getOpenTopographySlots(),
            write = ::setOpenTopographySlots,
            activeId = activeOpenTopographySlotId,
            setActiveId = { activeOpenTopographySlotId = it },
            slotId = slotId, status = status, lastError = lastError
        )
    }

    /** Mirrors recordOpenTopographyResult() exactly. Note that a
     * Copernicus quota failure shouldn't auto-advance either, for a
     * different reason than OpenTopography's: every client_id/secret
     * pair under one Copernicus account shares the same account-level
     * quota, so switching slots on a 429 would just retry against an
     * equally-exhausted pool. */
    fun recordCopernicusResult(slotId: String, status: CredentialStatus, lastError: String?) {
        recordResult(
            slots = getCopernicusSlots(),
            write = ::setCopernicusSlots,
            activeId = activeCopernicusSlotId,
            setActiveId = { activeCopernicusSlotId = it },
            slotId = slotId, status = status, lastError = lastError
        )
    }

    // ---- shared helpers ----

    private fun resolveActiveSlot(slots: List<CredentialSlot>, activeId: String?): CredentialSlot? {
        if (slots.isEmpty()) return null
        return slots.firstOrNull { it.id == activeId } ?: slots.first()
    }

    private fun recordResult(
        slots: List<CredentialSlot>,
        write: (List<CredentialSlot>) -> Unit,
        activeId: String?,
        setActiveId: (String) -> Unit,
        slotId: String,
        status: CredentialStatus,
        lastError: String?
    ) {
        val now = System.currentTimeMillis()
        val updated = slots.map {
            if (it.id == slotId) it.copy(status = status, lastError = lastError, lastTestedAtMillis = now) else it
        }
        write(updated)

        if (status == CredentialStatus.INVALID && activeId == slotId) {
            val nextGood = updated.firstOrNull { it.id != slotId && it.status != CredentialStatus.INVALID }
            if (nextGood != null) setActiveId(nextGood.id)
        }
    }

    private fun readSlots(key: String): List<CredentialSlot> {
        val raw = prefs.getString(key, null) ?: return emptyList()
        return try {
            val arr = JSONArray(raw)
            (0 until arr.length()).map { CredentialSlot.fromJson(arr.getJSONObject(it)) }
        } catch (e: Exception) {
            emptyList()
        }
    }

    private fun writeSlots(key: String, slots: List<CredentialSlot>) {
        val arr = JSONArray()
        slots.forEach { arr.put(it.toJson()) }
        prefs.edit().putString(key, arr.toString()).apply()
    }

    /** One-time migration from this class's previous single-value shape.
     * Safe to run on every construction since it only acts when the new
     * slot-list key is genuinely still unset. */
    private fun migrateLegacyValuesIfNeeded() {
        val legacyApiKey = prefs.getString(LEGACY_KEY_OPENTOPOGRAPHY_API_KEY, "") ?: ""
        if (legacyApiKey.isNotEmpty() && prefs.getString(KEY_OPENTOPO_SLOTS, null) == null) {
            val slot = CredentialSlot(id = "migrated-opentopo-1", primaryValue = legacyApiKey)
            setOpenTopographySlots(listOf(slot))
            activeOpenTopographySlotId = slot.id
        }

        val legacyClientId = prefs.getString(LEGACY_KEY_COPERNICUS_CLIENT_ID, "") ?: ""
        val legacyClientSecret = prefs.getString(LEGACY_KEY_COPERNICUS_CLIENT_SECRET, "") ?: ""
        if (legacyClientId.isNotEmpty() && prefs.getString(KEY_COPERNICUS_SLOTS, null) == null) {
            val slot = CredentialSlot(
                id = "migrated-copernicus-1",
                primaryValue = legacyClientId,
                secondaryValue = legacyClientSecret
            )
            setCopernicusSlots(listOf(slot))
            activeCopernicusSlotId = slot.id
        }
    }

    companion object {
        private const val PREFS_FILE_NAME = "ariyan_secure_credentials"

        // New multi-slot keys.
        private const val KEY_DEM_TYPE = "dem_type"
        private const val KEY_OPENTOPO_SLOTS = "opentopo_slots_json"
        private const val KEY_OPENTOPO_ACTIVE_ID = "opentopo_active_slot_id"
        private const val KEY_COPERNICUS_SLOTS = "copernicus_slots_json"
        private const val KEY_COPERNICUS_ACTIVE_ID = "copernicus_active_slot_id"

        // Legacy single-value keys -- read-only, for one-time migration.
        // Exact key names from this class's previous version.
        private const val LEGACY_KEY_OPENTOPOGRAPHY_API_KEY = "opentopography_api_key"
        private const val LEGACY_KEY_COPERNICUS_CLIENT_ID = "copernicus_client_id"
        private const val LEGACY_KEY_COPERNICUS_CLIENT_SECRET = "copernicus_client_secret"
    }
}
