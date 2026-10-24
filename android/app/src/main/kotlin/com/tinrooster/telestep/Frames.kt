package com.tinrooster.telestep

import android.accessibilityservice.AccessibilityService
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Rect
import android.os.Handler
import android.os.SystemClock
import android.view.Display
import com.tinrooster.telestep.core.Frame
import java.io.ByteArrayOutputStream
import kotlin.math.min
import kotlin.math.roundToInt

/** A screenshot as taken, plus the areas to hide when it is saved. */
class Shot(val bitmap: Bitmap, val hide: List<Rect>, val atMs: Long)

/**
 * Keeps a recent screenshot of the screen as it was BEFORE the next tap.
 *
 * Accessibility tap events arrive after the tap, when the app may already be changing the screen, so the picture for
 * a step is the one taken when the screen last settled.  takeScreenshot is limited to about three a second, so
 * requests are spaced out and screen changes are debounced.
 *
 * Our own floating button is kept out of the pictures by making it invisible for the moment of the screenshot
 * ([ownViews]); blurring it by position failed on real phones, where the reported window position was off by the
 * status bar.
 */
class FrameCache(
    private val service: AccessibilityService,
    private val main: Handler,
    private val hideRects: () -> List<Rect>,
    private val ownViews: (visible: Boolean) -> Unit = {},
) {
    @Volatile
    var latest: Shot? = null
        private set
    private var lastRequestMs = 0L
    private var running = false
    private val grab = Runnable { capture { latest = it } }

    fun start() {
        running = true
        latest = null
        main.post(grab)
    }

    fun stop() {
        running = false
        main.removeCallbacks(grab)
        latest = null
    }

    /** The screen changed: take a new "before" picture once it has been still for a moment. */
    fun screenChanged() {
        if (!running) return
        main.removeCallbacks(grab)
        main.postDelayed(grab, SETTLE_MS)
    }

    /** Take a screenshot now (or as soon as the rate limit allows) and hand it to [done] on the main thread. */
    fun capture(done: (Shot) -> Unit) {
        if (!running) return
        val wait = lastRequestMs + MIN_INTERVAL_MS - SystemClock.uptimeMillis()
        if (wait > 0) {
            main.postDelayed({ capture(done) }, wait)
            return
        }
        lastRequestMs = SystemClock.uptimeMillis()
        val hide = try {
            hideRects()
        } catch (e: Exception) {
            emptyList()
        }
        ownViews(false)
        main.postDelayed({ take(hide, done) }, HIDE_MS)  // give the change a few frames to reach the screen
    }

    private fun take(hide: List<Rect>, done: (Shot) -> Unit) {
        try {
            service.takeScreenshot(Display.DEFAULT_DISPLAY, service.mainExecutor, Taken(hide, done))
        } catch (e: Exception) {
            ownViews(true)
        }
    }

    private inner class Taken(val hide: List<Rect>, val done: (Shot) -> Unit) : AccessibilityService.TakeScreenshotCallback {
        override fun onSuccess(result: AccessibilityService.ScreenshotResult) {
            ownViews(true)
            val buffer = result.hardwareBuffer
            val bmp = try {
                Bitmap.wrapHardwareBuffer(buffer, result.colorSpace)?.copy(Bitmap.Config.ARGB_8888, false)
            } finally {
                buffer.close()
            }
            if (bmp != null && running) done(Shot(bmp, hide, SystemClock.uptimeMillis()))
        }

        override fun onFailure(errorCode: Int) {
            // Secure windows (banking apps, lock screen) refuse screenshots: the step is kept without one.
            ownViews(true)
        }
    }

    companion object {
        const val SETTLE_MS = 300L
        const val MIN_INTERVAL_MS = 350L
        const val HIDE_MS = 48L
    }
}

object Frames {
    /** Scale to at most [maxWidth], hide the given areas (pixelated), and encode as JPEG for the session. */
    fun encode(shot: Shot, maxWidth: Int = 1080, quality: Int = 85): Frame {
        val src = shot.bitmap
        val scale = min(1.0, maxWidth.toDouble() / src.width)
        val w = (src.width * scale).roundToInt().coerceAtLeast(1)
        val h = (src.height * scale).roundToInt().coerceAtLeast(1)
        val out = if (scale < 1.0) Bitmap.createScaledBitmap(src, w, h, true) else src.copy(Bitmap.Config.ARGB_8888, true)
        val mutable = if (out.isMutable) out else out.copy(Bitmap.Config.ARGB_8888, true)
        val canvas = Canvas(mutable)
        for (r in shot.hide) pixelate(canvas, mutable, scaled(r, scale, w, h))
        val bytes = ByteArrayOutputStream().also { mutable.compress(Bitmap.CompressFormat.JPEG, quality, it) }.toByteArray()
        return Frame(bytes, scale)
    }

    private fun scaled(r: Rect, s: Double, w: Int, h: Int) = Rect(
        (r.left * s).roundToInt().coerceIn(0, w), (r.top * s).roundToInt().coerceIn(0, h),
        (r.right * s).roundToInt().coerceIn(0, w), (r.bottom * s).roundToInt().coerceIn(0, h),
    )

    /** Coarse pixelation: shrink the area to a few blocks and draw it back without smoothing. */
    private fun pixelate(canvas: Canvas, bmp: Bitmap, r: Rect) {
        if (r.width() < 2 || r.height() < 2) return
        val part = Bitmap.createBitmap(bmp, r.left, r.top, r.width(), r.height())
        val block = 16
        val tiny = Bitmap.createScaledBitmap(part, (r.width() / block).coerceAtLeast(1), (r.height() / block).coerceAtLeast(1), true)
        val big = Bitmap.createScaledBitmap(tiny, r.width(), r.height(), false)
        canvas.drawBitmap(big, r.left.toFloat(), r.top.toFloat(), Paint())
    }
}
