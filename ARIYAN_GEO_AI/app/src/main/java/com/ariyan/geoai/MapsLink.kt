package com.ariyan.geoai

import android.content.ActivityNotFoundException
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.widget.Toast
import java.util.Locale

/**
 * maps-v1 (2026-11-02, user request): open a candidate's coordinates in Google
 * Maps for a sharper satellite look (Sentinel-2 is only 10 m per pixel). Tries
 * the Google Maps app, then any maps app, then the browser. Only the two
 * numbers and a short label leave the app; nothing is changed or saved.
 */
object MapsLink {

    fun coords(lat: Double, lon: Double): String = String.format(Locale.US, "%.5f,%.5f", lat, lon)

    fun open(ctx: Context, lat: Double, lon: Double, label: String) {
        val c = coords(lat, lon)
        val tag = Uri.encode("ARIYAN $label")
        val geo = Intent(Intent.ACTION_VIEW, Uri.parse("geo:$c?q=$c($tag)"))
        val web = Intent(Intent.ACTION_VIEW, Uri.parse("https://www.google.com/maps/search/?api=1&query=$c"))
        for (i in listOf(Intent(geo).setPackage("com.google.android.apps.maps"), geo, web)) {
            try {
                ctx.startActivity(i)
                return
            } catch (_: ActivityNotFoundException) {
            }
        }
        Toast.makeText(ctx, "No maps app or browser found. Coordinates: $c", Toast.LENGTH_LONG).show()
    }

    fun copy(ctx: Context, lat: Double, lon: Double) {
        val c = coords(lat, lon)
        (ctx.getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager)
            ?.setPrimaryClip(ClipData.newPlainText("coordinates", c))
        Toast.makeText(ctx, "Copied $c", Toast.LENGTH_SHORT).show()
    }
}
