// Kotlin is built in since AGP 9 (no kotlin-android plugin). Only open-source dependencies
// (AGENTS.md section 6); no Google Play services.
plugins {
    id("com.android.application")
}

android {
    namespace = "de.r80.companion"
    compileSdk = 36

    defaultConfig {
        applicationId = "de.r80.companion"
        minSdk = 34          // Android 14: the oldest test phone (D11)
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0"
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    buildFeatures {
        buildConfig = true
    }
    // the HU's own fonts (B612, OSP-DIN) with their licence files, as the app's assets: one source
    sourceSets["main"].assets.srcDir("../../hu/ui/fonts")
    testOptions {
        unitTests.isReturnDefaultValues = true
    }
}

dependencies {
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.11.0")
    testImplementation("junit:junit:4.13.2")
}
