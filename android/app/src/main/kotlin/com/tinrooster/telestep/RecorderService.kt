package com.tinrooster.telestep

import android.accessibilityservice.AccessibilityService
import android.content.pm.PackageManager
import android.graphics.Rect
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import com.tinrooster.telestep.core.Describe
import com.tinrooster.telestep.core.Place
import com.tinrooster.telestep.core.Session
import com.tinrooster.telestep.core.StepRecorder
import com.tinrooster.telestep.core.Target
import java.io.File
import java.util.concurrent.Executors

/**
 * The step recorder.  Runs while the user has it switched on in Accessibility settings, but records nothing until a
 * recording is started (floating button or the app).  Taps, long presses, scrolls, typing and dialogs become steps in
 * a desktop-format session under the app's files folder.
 */
class RecorderService : AccessibilityService() {
    private val main = Handler(Looper.getMainLooper())
    private val io = Executors.newSingleThreadExecutor()  // JPEG encoding and file writes, in step order
    private lateinit var frames: FrameCache
    private var overlay: Overlay? = null
    private var recorder: StepRecorder? = null
    private val places = HashMap<String, Place>()  // package -> app label, version and its current screen title

    var session: Session? = null
        private set
    var paused = false
        private set
    val recording get() = recorder != null

    override fun onServiceConnected() {
        instance = this
        frames = FrameCache(this, main) { hiddenAreas() }
        overlay = Overlay(this).also { it.show() }
        notifyChanged()
    }

    override fun onDestroy() {
        stopRecording()
        overlay?.remove()
        overlay = null
        if (instance === this) instance = null
        notifyChanged()
        io.shutdown()
        super.onDestroy()
    }

    override fun onInterrupt() {}

    // ------------------------------------------------------------------ recording on / off
    fun startRecording(): Session {
        session?.let { if (recording) return it }
        val dir = File(Recordings.root(this), Session.dirName())
        val s = Session(dir, host = Recordings.deviceName(this), environment = Recordings.environment(this))
        s.makeDirs()
        s.save()
        val prefs = Prefs.of(this)
        recorder = StepRecorder(s, prefs.keyMode)
        session = s
        paused = false
        places.clear()
        frames.start()
        notifyChanged()
        return s
    }

    fun stopRecording(): Session? {
        val s = session ?: return null
        recorder = null
        session = null
        paused = false
        frames.stop()
        io.execute { s.save() }
        notifyChanged()
        return s
    }

    fun toggleRecording() {
        if (recording) stopRecording() else startRecording()
    }

    fun togglePause() {
        if (!recording) return
        paused = !paused
        if (!paused) frames.screenChanged()
        notifyChanged()
    }

    private fun notifyChanged() {
        overlay?.refresh()
        listeners.forEach { it() }
    }

    // ------------------------------------------------------------------ events
    override fun onAccessibilityEvent(e: AccessibilityEvent) {
        val rec = recorder ?: return
        if (paused || e.packageName?.toString() == packageName) return  // never record our own button or app
        when (e.eventType) {
            AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED -> {
                rememberPlace(e)
                frames.screenChanged()
                if (Prefs.of(this).dialogs && e.className?.toString()?.contains("Dialog") == true) onDialog(rec, e)
            }
            AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED -> frames.screenChanged()
            AccessibilityEvent.TYPE_VIEW_CLICKED -> onTap(rec, e, false)
            AccessibilityEvent.TYPE_VIEW_LONG_CLICKED -> onTap(rec, e, true)
            AccessibilityEvent.TYPE_VIEW_SCROLLED -> onScroll(rec, e)
            AccessibilityEvent.TYPE_VIEW_TEXT_CHANGED -> onText(rec, e)
        }
    }

    private fun target(node: AccessibilityNodeInfo?): Target =
        node?.let { Describe.target(NodeAdapter(it)) } ?: Target("", "", false, null, false)

    private fun onTap(rec: StepRecorder, e: AccessibilityEvent, long: Boolean) {
        val t = target(e.source)
        val b = t.bounds
        val (x, y) = if (b != null) ((b[0] + b[2]) / 2) to ((b[1] + b[3]) / 2) else 0 to 0
        val shot = frames.latest
        val place = placeFor(e)
        val after = Prefs.of(this).afterShot
        io.execute {
            val step = rec.tap(t, x, y, place, shot?.let { Frames.encode(it) }, long)
            if (after) {
                main.postDelayed({ frames.capture { s -> io.execute { rec.after(step, Frames.encode(s)) } } }, AFTER_MS)
            }
        }
        frames.screenChanged()
    }

    private fun onScroll(rec: StepRecorder, e: AccessibilityEvent) {
        val t = target(e.source)
        val dir = when {
            e.scrollDeltaY > 0 -> "down"
            e.scrollDeltaY < 0 -> "up"
            e.scrollDeltaX > 0 -> "right"
            e.scrollDeltaX < 0 -> "left"
            else -> return
        }
        val b = t.bounds
        val (x, y) = if (b != null) ((b[0] + b[2]) / 2) to ((b[1] + b[3]) / 2) else 0 to 0
        val shot = frames.latest
        val place = placeFor(e)
        val ms = SystemClock.uptimeMillis()
        io.execute { rec.scroll(t, dir, x, y, place, shot?.let { Frames.encode(it) }, ms) }
        frames.screenChanged()
    }

    private fun onText(rec: StepRecorder, e: AccessibilityEvent) {
        val node = e.source
        val t = target(node).let { if (e.isPassword && !it.password) it.copy(password = true) else it }
        val key = "${e.windowId}:${node?.viewIdResourceName}:${t.bounds?.joinToString(",")}"
        val text = e.text.joinToString("")
        val place = placeFor(e)
        io.execute { rec.text(key, t, text, place) }
    }

    private fun onDialog(rec: StepRecorder, e: AccessibilityEvent) {
        val place = placeFor(e)
        main.postDelayed({  // let the dialog finish drawing first
            val root = rootInActiveWindow ?: return@postDelayed
            val texts = Describe.texts(NodeAdapter(root))
            val title = texts.firstOrNull() ?: e.text.firstOrNull()?.toString().orEmpty()
            frames.capture { shot -> io.execute { rec.dialog(title, texts, place, Frames.encode(shot)) } }
        }, DIALOG_SETTLE_MS)
    }

    // ------------------------------------------------------------------ where a step happened
    private fun rememberPlace(e: AccessibilityEvent) {
        val pkg = e.packageName?.toString() ?: return
        val base = places[pkg] ?: appPlace(pkg)
        val title = e.text.firstOrNull()?.toString()?.takeIf { it.isNotBlank() }
            ?: e.className?.toString()?.substringAfterLast('.').orEmpty()
        places[pkg] = base.copy(window = Describe.clean(title))
    }

    private fun placeFor(e: AccessibilityEvent): Place {
        val pkg = e.packageName?.toString() ?: return Place()
        return places.getOrPut(pkg) { appPlace(pkg) }
    }

    private fun appPlace(pkg: String): Place = try {
        val pm = packageManager
        val label = pm.getApplicationLabel(pm.getApplicationInfo(pkg, 0)).toString()
        val version = pm.getPackageInfo(pkg, 0).versionName.orEmpty()
        Place(label, version, "")
    } catch (e: PackageManager.NameNotFoundException) {
        Place(pkg, "", "")
    }

    /** Password fields on screen, and our own floating button: hidden in every screenshot. */
    private fun hiddenAreas(): List<Rect> {
        val roots = windows.mapNotNull { it.root }
        return passwordRects(roots) + listOfNotNull(overlay?.screenRect())
    }

    companion object {
        const val AFTER_MS = 700L
        const val DIALOG_SETTLE_MS = 300L

        @Volatile
        var instance: RecorderService? = null
            private set
        val listeners = mutableListOf<() -> Unit>()
    }
}
