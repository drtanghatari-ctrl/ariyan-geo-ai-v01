plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

android {
    namespace = "com.ariyan.geoai"
    compileSdk = 35

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
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.constraintlayout:constraintlayout:2.1.4")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.4")
    implementation("androidx.activity:activity-ktx:1.9.1")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")

    testImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.6.1")
}
