package com.ariyan.geoai

import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.Settings
import androidx.core.content.ContextCompat
import java.io.File

/**
 * ExternalStorageAccess -- real shared-storage access for offline country
 * data, replacing the app-private internal storage previously used, and
 * replacing the Google Drive backup mechanism (DriveBackupWorker.kt,
 * deleted this session) that existed only because app-private storage
 * doesn't survive an uninstall.
 *
 * User's own explicit choice this session: point downloads at real shared
 * storage instead -- survives an uninstall on its own, no cloud account,
 * no OAuth, no Google Cloud Console setup. The one real cost: a
 * broad-sounding on-device permission (MANAGE_EXTERNAL_STORAGE, "All
 * files access"), explained plainly before the user agreed to it; this
 * app is sideloaded, never distributed via Google Play, so Play's policy
 * restrictions on this permission don't apply here.
 *
 * TWO PERMISSION MODELS, version-gated (confirmed against Android's
 * current official "Manage all files on a storage device" docs before
 * writing this):
 *   - Android 11+ (API 30+): MANAGE_EXTERNAL_STORAGE, only grantable via
 *     a system Settings screen -- Environment.isExternalStorageManager()
 *     to check, Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION
 *     (per-app deep link) to request it.
 *   - Android 10 and below (API < 30): a normal runtime
 *     WRITE_EXTERNAL_STORAGE permission is enough, requested the same way
 *     ACCESS_FINE_LOCATION already is elsewhere in this app.
 *
 * HONEST STATE: straightforward, well-documented AndroidX/platform API
 * usage, but NOT yet run on an actual device to confirm the permission
 * grant flow and resulting real file writes both work end to end.
 */
object ExternalStorageAccess {

    /** Where this app's offline DEM+NDVI downloads live: a real,
     * human-visible folder under shared storage, not this app's private,
     * uninstall-wiped storage. */
    fun offlineDataRoot(): File =
        File(Environment.getExternalStorageDirectory(), "ARIYAN_GEO_AI/offline_data")

    /** True if this app can currently read/write real file paths under
     * shared storage -- version-gated, see class doc comment. */
    fun isGranted(context: Context): Boolean {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            Environment.isExternalStorageManager()
        } else {
            ContextCompat.checkSelfPermission(
                context, android.Manifest.permission.WRITE_EXTERNAL_STORAGE
            ) == PackageManager.PERMISSION_GRANTED
        }
    }

    /** The per-app "All files access" settings screen for this app
     * (Android 11+ only). Some OEM builds don't support the per-app deep
     * link; callers should catch ActivityNotFoundException and fall back
     * to Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION if that
     * happens. */
    fun manageAllFilesSettingsIntent(context: Context): Intent =
        Intent(
            Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION,
            Uri.parse("package:${context.packageName}")
        )
}