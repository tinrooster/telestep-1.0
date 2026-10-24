package com.tinrooster.telestep.core

import java.io.File
import java.time.LocalTime
import java.time.format.DateTimeFormatter
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream
import kotlin.math.roundToInt

/** A screenshot ready to save: JPEG bytes; saved pixels = screen pixels * scale. */
class Frame(val jpeg: ByteArray, val scale: Double)

/** Where a step happened: app label, its version, and the screen (window) title. */
data class Place(val app: String = "", val version: String = "", val window: String = "")

/**
 * Turns touches into steps, the way the desktop recorder does for clicks: one step per tap with its screenshot and
 * marker, scrolls in the same list merged into one step, typing in one field merged into one step.
 */
class StepRecorder(
    val session: Session,
    var keyMode: String = "count",  // off | count | text
    private val clock: () -> LocalTime = { LocalTime.now() },
) {
    private var lastScroll: Step? = null
    private var lastScrollKey = ""
    private var lastScrollMs = 0L
    private var lastType: Step? = null
    private var lastTypeKey = ""

    @Synchronized
    fun tap(t: Target, x: Int, y: Int, place: Place, frame: Frame?, longPress: Boolean = false): Step {
        breakRuns()
        val (friendly, tech) = Captions.tap(t, x, y, longPress)
        val st = newStep("click", friendly, tech, place)
        st.el = linkedMapOf("name" to t.name, "kind" to t.kind, "inherited" to t.inherited, "button" to "left",
            "x" to x, "y" to y, "touch" to if (longPress) "long" else "tap")
        if (frame != null) {
            st.raw = saveImage(st.id, frame, "")
            st.geom = geom(frame)
            st.marker = linkedMapOf("shape" to "click", "pt" to pt(frame, x, y),
                "rect" to t.bounds?.let { b -> pt(frame, b[0], b[1]) + pt(frame, b[2], b[3]) }, "win" to null)
        } else {
            st.marker = mapOf("shape" to "none")
        }
        return session.add(st)
    }

    /** The screen as it looked just after the tap (the desktop's "after-click capture"). */
    @Synchronized
    fun after(step: Step, frame: Frame) {
        step.rawAfter = saveImage(step.id, frame, "_after")
        session.save()
    }

    /** Returns the new step, or null when the scroll continued the previous one (same list, same direction). */
    @Synchronized
    fun scroll(t: Target, direction: String, x: Int, y: Int, place: Place, frame: Frame?, ms: Long): Step? {
        val key = "${place.app}|${t.name}|${t.kind}|$direction"
        val prev = lastScroll
        if (prev != null && key == lastScrollKey && ms - lastScrollMs < 2500) {
            lastScrollMs = ms
            return null
        }
        breakRuns()
        val (friendly, tech) = Captions.scroll(direction, t.name)
        val st = newStep("scroll", friendly, tech, place)
        if (frame != null) {
            st.raw = saveImage(st.id, frame, "")
            st.geom = geom(frame)
            st.marker = linkedMapOf("shape" to "scroll", "pt" to pt(frame, x, y), "dir" to direction, "win" to null)
        } else {
            st.marker = mapOf("shape" to "none")
        }
        lastScroll = st
        lastScrollKey = key
        lastScrollMs = ms
        return session.add(st)
    }

    /** Text typed into a field.  Returns the new step, or null when it updated the step for the same field. */
    @Synchronized
    fun text(fieldKey: String, t: Target, text: String, place: Place): Step? {
        if (keyMode == "off") return null
        val (friendly, tech) = Captions.type(keyMode, if (t.password) "" else text, text.length, t.password)
        val prev = lastType
        if (prev != null && fieldKey == lastTypeKey) {
            prev.friendly = friendly
            prev.tech = tech
            session.save()
            return null
        }
        breakRuns()
        val st = newStep("type", friendly, tech, place)
        lastType = st
        lastTypeKey = fieldKey
        return session.add(st)
    }

    @Synchronized
    fun dialog(title: String, texts: List<String>, place: Place, frame: Frame?): Step {
        breakRuns()
        val (friendly, tech) = Captions.dialog(title)
        val st = newStep("dialog", friendly, tech, place)
        st.dialogText = texts.joinToString("\n")
        st.marker = mapOf("shape" to "none")
        if (frame != null) {
            st.raw = saveImage(st.id, frame, "")
            st.geom = geom(frame)
        }
        return session.add(st)
    }

    private fun breakRuns() {
        lastScroll = null
        lastType = null
    }

    private fun newStep(kind: String, friendly: String, tech: String, place: Place) =
        Step(Session.newId(), kind, clock().format(TIME)).apply {
            this.friendly = friendly
            this.tech = tech
            app = place.app
            appVersion = place.version
            window = place.window
        }

    private fun saveImage(id: String, frame: Frame, suffix: String): String {
        val rel = "raw/$id$suffix.jpg"
        val f = File(session.dir, rel)
        f.parentFile?.mkdirs()
        f.writeBytes(frame.jpeg)
        return rel
    }

    private fun geom(frame: Frame) = linkedMapOf("left" to 0, "top" to 0, "scale" to frame.scale)

    private fun pt(frame: Frame, x: Int, y: Int): List<Double> =
        listOf(round1(x * frame.scale), round1(y * frame.scale))

    private fun round1(v: Double) = (v * 10).roundToInt() / 10.0

    companion object {
        private val TIME = DateTimeFormatter.ofPattern("HH:mm:ss")
    }
}

object Export {
    /**
     * Zip a recording for the desktop: entries sit under the recording's folder name, so unzipping into the desktop's
     * recordings folder gives a session it lists and opens.
     */
    fun zip(sessionDir: File, out: File) {
        val base = sessionDir.name
        ZipOutputStream(out.outputStream().buffered()).use { zip ->
            sessionDir.walkTopDown().filter { it.isFile && !it.name.endsWith(".tmp") }.sortedBy { it.path }.forEach { f ->
                val rel = f.relativeTo(sessionDir).invariantSeparatorsPath
                zip.putNextEntry(ZipEntry("$base/$rel"))
                f.inputStream().use { it.copyTo(zip) }
                zip.closeEntry()
            }
        }
    }
}
