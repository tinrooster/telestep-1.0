pluginManagement {
    repositories {
        google {
            content {  // only Android / Google artifacts come from Google's repository
                includeGroupByRegex("com\\.android.*")
                includeGroupByRegex("com\\.google.*")
                includeGroupByRegex("androidx.*")
            }
        }
        mavenCentral()
        gradlePluginPortal()
    }
    plugins {
        id("com.android.application") version "8.7.3"
        id("org.jetbrains.kotlin.android") version "2.1.0"
        id("org.jetbrains.kotlin.jvm") version "2.1.0"
    }
}

dependencyResolutionManagement {
    repositories {
        google {
            content {  // only Android / Google artifacts come from Google's repository
                includeGroupByRegex("com\\.android.*")
                includeGroupByRegex("com\\.google.*")
                includeGroupByRegex("androidx.*")
            }
        }
        mavenCentral()
    }
}

rootProject.name = "telestep-android"
include(":core")
// -PcoreOnly=true builds and tests the plain-Kotlin core without the Android Gradle plugin (no Android SDK needed).
if (providers.gradleProperty("coreOnly").orNull != "true") {
    include(":app")
}
