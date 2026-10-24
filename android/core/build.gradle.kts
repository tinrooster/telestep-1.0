import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    id("org.jetbrains.kotlin.jvm")
}

java {
    sourceCompatibility = JavaVersion.VERSION_17
    targetCompatibility = JavaVersion.VERSION_17
}

kotlin {
    compilerOptions { jvmTarget.set(JvmTarget.JVM_17) }
}

dependencies {
    testImplementation(kotlin("test-junit"))
}

tasks.test {
    // -PsampleOut=<folder> also writes the test recording there (the desktop suite opens it: tests/test_android_session.py)
    providers.gradleProperty("sampleOut").orNull?.let { systemProperty("telestep.sampleOut", it) }
}
