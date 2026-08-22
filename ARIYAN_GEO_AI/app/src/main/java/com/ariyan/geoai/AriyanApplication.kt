package com.ariyan.geoai

import android.app.Application
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform

/**
 * Starts the embedded Python interpreter exactly once, at process start.
 * Python.start() is idempotent-guarded by isStarted() so this is safe
 * even if something else tries to start it again later.
 */
class AriyanApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        if (!Python.isStarted()) {
            Python.start(AndroidPlatform(this))
        }
    }
}
