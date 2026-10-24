package com.tinrooster.telestep

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.PixelFormat
import android.graphics.Rect
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration
import android.view.WindowManager
import kotlin.math.abs

/**
 * The floating record button (an accessibility overlay, so no "draw over other apps" permission is needed).
 * Tap: start / stop.  Long press: pause / resume while recording, hide the button when not.  Drag: move it.
 * It is blurred out of every screenshot.
 */
class Overlay(private val service: RecorderService) {
    private val wm = service.getSystemService(Context.WINDOW_SERVICE) as WindowManager
    private val size = (52 * service.resources.displayMetrics.density).toInt()
    private val view = Badge(service)
    private val params = WindowManager.LayoutParams(
        size, size,
        WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
        WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
        PixelFormat.TRANSLUCENT,
    ).apply {
        gravity = Gravity.TOP or Gravity.START
        val dm = service.resources.displayMetrics
        x = dm.widthPixels - size - size / 4
        y = dm.heightPixels / 3
    }
    var shown = false
        private set

    @SuppressLint("ClickableViewAccessibility")
    fun show() {
        if (shown) return
        view.contentDescription = "Telestep recording button"
        view.setOnTouchListener(Drag())
        wm.addView(view, params)
        shown = true
    }

    fun remove() {
        if (shown) {
            try {
                wm.removeView(view)
            } catch (e: IllegalArgumentException) {
            }
            shown = false
        }
    }

    fun refresh() {
        view.state = when {
            !service.recording -> Badge.IDLE
            service.paused -> Badge.PAUSED
            else -> Badge.RECORDING
        }
        view.invalidate()
    }

    /**
     * Where the button really is on screen (what the screenshots show).  Not params.x/y: Android places the window
     * below the status bar and keeps it inside the screen, so the requested position can be well off.
     */
    fun screenRect(): Rect? {
        if (!shown || !view.isAttachedToWindow) return null
        val at = IntArray(2)
        view.getLocationOnScreen(at)
        val pad = size / 8  // the antialiased edge
        return Rect(at[0] - pad, at[1] - pad, at[0] + view.width + pad, at[1] + view.height + pad)
    }

    private inner class Drag : View.OnTouchListener {
        private val slop = ViewConfiguration.get(service).scaledTouchSlop
        private var downX = 0f
        private var downY = 0f
        private var startX = 0
        private var startY = 0
        private var moved = false
        private var longDone = false
        private val longPress = Runnable {
            if (!moved) {
                longDone = true
                if (service.recording) service.togglePause() else service.hideButton()
            }
        }

        override fun onTouch(v: View, ev: MotionEvent): Boolean {
            when (ev.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    downX = ev.rawX
                    downY = ev.rawY
                    startX = params.x
                    startY = params.y
                    moved = false
                    longDone = false
                    v.postDelayed(longPress, ViewConfiguration.getLongPressTimeout().toLong())
                }
                MotionEvent.ACTION_MOVE -> {
                    val dx = ev.rawX - downX
                    val dy = ev.rawY - downY
                    if (moved || abs(dx) > slop || abs(dy) > slop) {
                        moved = true
                        v.removeCallbacks(longPress)
                        params.x = (startX + dx).toInt()
                        params.y = (startY + dy).toInt()
                        wm.updateViewLayout(view, params)
                    }
                }
                MotionEvent.ACTION_UP -> {
                    v.removeCallbacks(longPress)
                    if (!moved && !longDone) service.toggleRecording()
                }
                MotionEvent.ACTION_CANCEL -> v.removeCallbacks(longPress)
            }
            return true
        }
    }
}

/** Round button: blue with a red dot when idle (tap to record), red with a white square while recording. */
class Badge(context: Context) : View(context) {
    var state = IDLE
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG)

    override fun onDraw(canvas: Canvas) {
        val r = width / 2f
        paint.color = when (state) {
            RECORDING -> Color.rgb(229, 57, 53)
            PAUSED -> Color.rgb(245, 158, 11)
            else -> Color.rgb(21, 101, 192)
        }
        paint.alpha = 230
        canvas.drawCircle(r, r, r, paint)
        paint.alpha = 255
        when (state) {
            IDLE -> {
                paint.color = Color.rgb(229, 57, 53)
                canvas.drawCircle(r, r, r * 0.38f, paint)
            }
            RECORDING -> {
                paint.color = Color.WHITE
                val s = r * 0.36f
                canvas.drawRect(r - s, r - s, r + s, r + s, paint)
            }
            PAUSED -> {
                paint.color = Color.WHITE
                val w = r * 0.16f
                val h = r * 0.4f
                canvas.drawRect(r - 2.2f * w, r - h, r - 0.6f * w, r + h, paint)
                canvas.drawRect(r + 0.6f * w, r - h, r + 2.2f * w, r + h, paint)
            }
        }
    }

    companion object {
        const val IDLE = 0
        const val RECORDING = 1
        const val PAUSED = 2
    }
}
