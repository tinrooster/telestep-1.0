package com.tinrooster.telestep.core

import java.io.File
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter
import java.util.UUID

/**
 * A recording in the desktop Telestep format (telestep_model.py, FORMAT_VERSION 2): a folder with session.json and
 * the screenshots in raw/.  The desktop review editor and every exporter open it as is.
 */
const val FORMAT_VERSION = 2
const val RECORDER_VERSION = "Android 0.1"

class Step(val id: String, var kind: String, val time: String) {
    var friendly = ""
    var tech = ""
    var window = ""
    var app = ""
    var appVersion = ""
    var dialogText = ""
    var raw = ""
    var rawAfter = ""
    var marker: Map<String, Any?>? = null
    var geom: Map<String, Any?>? = null
    var el: Map<String, Any?>? = null
    var comment = ""

    /** Same keys as the desktop Step dataclass, so Session.load there fills every field. */
    fun toMap(): Map<String, Any?> = linkedMapOf(
        "id" to id, "kind" to kind, "when" to time, "friendly" to friendly, "tech" to tech, "custom" to "",
        "level" to "", "window" to window, "app" to app, "app_version" to appVersion, "dialog_text" to dialogText,
        "raw" to raw, "raw_after" to rawAfter, "image" to "", "image_after" to "", "marker" to marker, "geom" to geom,
        "el" to el, "skip" to false, "auto" to false, "comment" to comment, "audio" to "", "apos" to -1.0,
        "path" to null, "marks" to null,
    )
}

class Session(
    val dir: File,
    var title: String = "Recorded steps",
    val host: String = "",
    val environment: Map<String, String> = emptyMap(),
    val created: String = LocalDateTime.now().withNano(0).toString(),
) {
    val steps = mutableListOf<Step>()
    val rawDir get() = File(dir, "raw")

    fun makeDirs() {
        rawDir.mkdirs()
        File(dir, "images").mkdirs()
    }

    @Synchronized
    fun add(step: Step): Step {
        steps.add(step)
        save()
        return step
    }

    /** Atomic write, so a crash mid-save can't corrupt the session. */
    @Synchronized
    fun save(): Boolean = try {
        dir.mkdirs()
        val tmp = File(dir, "session.json.tmp")
        tmp.writeText(Json.write(toMap()), Charsets.UTF_8)
        Files.move(tmp.toPath(), File(dir, "session.json").toPath(),
            StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE)
        true
    } catch (e: Exception) {
        false
    }

    @Synchronized
    fun toMap(): Map<String, Any?> = linkedMapOf(
        "format" to FORMAT_VERSION, "recorder" to RECORDER_VERSION, "title" to title, "created" to created,
        "host" to host, "environment" to environment, "settings" to emptyMap<String, Any>(),
        "steps" to steps.map { it.toMap() },
    )

    companion object {
        fun newId(): String = UUID.randomUUID().toString().replace("-", "").take(8)

        /** '20261022_182830', the desktop's folder name for a recording. */
        fun dirName(now: LocalDateTime = LocalDateTime.now()): String =
            now.format(DateTimeFormatter.ofPattern("yyyyMMdd_HHmmss"))
    }
}
