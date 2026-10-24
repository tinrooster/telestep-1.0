plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.tinrooster.telestep"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.tinrooster.telestep"
        minSdk = 30  // Android 11: the accessibility service takes the screenshots itself (no screen-cast prompt)
        targetSdk = 35
        versionCode = 1
        versionName = "0.1"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    // No AndroidX: the app uses the framework only, so it stays small and needs nothing from Google's repository.
    implementation(project(":core"))
}
