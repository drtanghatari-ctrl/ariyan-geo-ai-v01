plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

android {
    namespace = "com.ariyan.geoai"
    compileSdk = 35

    signingConfigs {
        getByName("debug") {
            // Pinned debug keystore checked into the repo (app/debug.keystore)
            // so every GitHub Actions build machine signs the debug APK with
            // the SAME key. Without this, each fresh CI runner has no
            // ~/.android/debug.keystore, so AGP silently generates a brand-new
            // random one per build -- meaning every new APK download has a
            // different signature than the previously installed one, and
            // Android refuses to install-over-update it ("App signature
            // doesn't match"), forcing an uninstall before every reinstall.
            // This is a debug-only key (password "android", the standard
            // Android tooling convention, never used for release signing) --
            // committing it is standard practice and not a security concern.
            storeFile = file("debug.keystore")
            storePassword = "android"
            keyAlias = "androiddebugkey"
            keyPassword = "android"
        }
    }

    defaultConfig {
        applicationId = "com.ariyan.geoai"
        minSdk = 24
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0-android-vslice"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

        // Python is a native component under the hood (Chaquopy embeds a
        // real CPython build per ABI). Restricting to the two ABIs that
        // cover essentially all real Android devices keeps APK size sane;
        // add x86/x86_64 back in if you need emulator support on an
        // Intel-based dev machine.
        ndk {
            abiFilters += listOf("armeabi-v7a", "arm64-v8a")
        }
    }

    buildTypes {
        debug {
            signingConfig = signingConfigs.getByName("debug")
        }
        release {
            isMinifyEnabled = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        viewBinding = true
    }
}

chaquopy {
    defaultConfig {
        // Matches the Python version this core was written and tested
        // against (see ariyan_core README / test suite).
        version = "3.10"

        pip {
            // numpy: required by the whole pipeline (np_ops.py etc).
            // requests: used only by dem_source_mobile.py's real
            // OpenTopography fetch (use_real_dem=True path) -- it's a
            // pure-Python package, no native build step, unlike
            // scipy/matplotlib/rasterio which are deliberately NOT
            // listed here (see np_ops.py / dem_source_mobile.py for
            // why: scipy's native code and rasterio's GDAL dependency
            // are a poor fit for Chaquopy Android builds -- GDAL in
            // particular cannot be compiled by Chaquopy at all).
            install("numpy")
            install("requests")
        }
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("com.google.android.gms:play-services-location:21.3.0")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.constraintlayout:constraintlayout:2.1.4")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.4")
    implementation("androidx.activity:activity-ktx:1.9.1")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")

    // Offline mode (DriveBackupWorker.kt): background download+backup jobs.
    //
    // NOT the latest work-runtime-ktx (2.11.2) -- a real CI run confirmed
    // that version's AAR metadata requires Android Gradle plugin 8.6.0+,
    // while this project is pinned to AGP 8.5.2 (see the `com.android.tools.build:gradle`
    // classpath in the project-level build.gradle.kts). This turns out to
    // be part of a broader, ongoing AndroidX-wide trend of newer library
    // releases quietly raising their required AGP floor (androidx.core-ktx
    // hit the exact same AGP-8.6.0 wall at its own 1.16.0 release, for
    // example) -- rather than bump this whole Chaquopy-based project's AGP
    // version to chase it (a much bigger, riskier, less-isolated change,
    // against this project's established minimal-footprint discipline),
    // pinned to 2.9.1 instead: an established, long-stable release that
    // predates this AGP-floor trend, and whose API surface (CoroutineWorker,
    // WorkerParameters, workDataOf, setProgressAsync) has been stable since
    // long before 2.9.1 -- nothing DriveBackupWorker.kt uses is new enough
    // to require a newer release. To be confirmed for real via this same
    // CI build.
    implementation("androidx.work:work-runtime-ktx:2.9.1")
    // Offline mode (DriveBackupWorker.kt): current (non-deprecated)
    // AuthorizationClient API for requesting the narrow drive.file scope
    // and obtaining a Drive access token -- deliberately NOT the older,
    // heavier GoogleSignInClient/GoogleApiClient (Google Sign-In for
    // Android is deprecated). Version + API surface confirmed against
    // Google's current official Android Identity documentation before
    // adding this. Unlike work-runtime-ktx above, this version did NOT
    // trigger an AGP-floor AAR metadata error in the same real CI run.
    implementation("com.google.android.gms:play-services-auth:21.5.1")

    testImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.6.1")
}
