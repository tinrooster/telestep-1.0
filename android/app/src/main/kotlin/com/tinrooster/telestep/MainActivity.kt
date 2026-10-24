package com.tinrooster.telestep

import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.graphics.Typeface
import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.CheckBox
import android.widget.LinearLayout
import android.widget.RadioButton
import android.widget.RadioGroup
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast

/** Setup, settings and the list of recordings.  Plain framework views: no libraries. */
class MainActivity : Activity() {
    private lateinit var status: TextView
    private lateinit var btnService: Button
    private lateinit var btnRecord: Button
    private lateinit var btnButton: Button
    private lateinit var btnOff: Button
    private lateinit var list: LinearLayout
    private val onServiceChange: () -> Unit = { runOnUiThread { refresh() } }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val pad = dp(16)
        val col = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(pad, pad, pad, pad)
        }
        col.addView(text("Telestep records the steps you take in other apps: which buttons you tap, with a " +
            "screenshot of each, so you can turn them into a how-to or a support ticket. Nothing leaves the phone " +
            "unless you share a recording.", 15f))
        status = text("", 15f, bold = true).also { col.addView(it, margins(top = 12)) }
        btnService = Button(this).apply {
            text = "Turn on Telestep in Accessibility settings"
            setOnClickListener { startActivity(Intent(android.provider.Settings.ACTION_ACCESSIBILITY_SETTINGS)) }
        }
        col.addView(btnService)
        col.addView(text("Installed from a file? If Android says the setting is restricted: open App info for " +
            "Telestep, tap ⋮ (top right) > Allow restricted settings, then try again.", 13f, gray = true))
        btnRecord = Button(this).apply {
            setOnClickListener {
                val svc = RecorderService.instance ?: return@setOnClickListener
                if (svc.recording) {
                    svc.stopRecording()
                } else {
                    svc.startRecording()
                    moveTaskToBack(true)  // get out of the way: the floating button stops the recording
                }
            }
        }
        col.addView(btnRecord, margins(top = 8))
        btnButton = Button(this).apply {
            setOnClickListener {
                val svc = RecorderService.instance ?: return@setOnClickListener
                if (svc.buttonShown) svc.hideButton() else svc.showButton()
            }
        }
        col.addView(btnButton)
        col.addView(text("Floating button: tap to start or stop a recording, press and hold to pause (or, when not " +
            "recording, to hide it), drag to move it. It only appears when you start a recording or show it here.",
            13f, gray = true))
        btnOff = Button(this).apply {
            text = "Turn off Telestep"
            setOnClickListener { RecorderService.instance?.turnOff() }
        }
        col.addView(btnOff, margins(top = 8))
        col.addView(text("Switches the recorder off completely (it stays off after a restart). Turn it on again in " +
            "Accessibility settings when you next want to record.", 13f, gray = true))

        col.addView(text("Typed text", 16f, bold = true), margins(top = 20))
        val prefs = Prefs.of(this)
        val modes = listOf("off" to "Don't record typing", "count" to "Record how many characters",
            "text" to "Record the text (never passwords)")
        val group = RadioGroup(this)
        modes.forEachIndexed { i, (key, label) ->
            group.addView(RadioButton(this).apply {
                id = 1000 + i
                text = label
                isChecked = prefs.keyMode == key
            })
        }
        group.setOnCheckedChangeListener { _, id -> prefs.keyMode = modes[id - 1000].first }
        col.addView(group)
        col.addView(CheckBox(this).apply {
            text = "Also capture the screen just after each tap"
            isChecked = prefs.afterShot
            setOnCheckedChangeListener { _, on -> prefs.afterShot = on }
        })
        col.addView(CheckBox(this).apply {
            text = "Record dialogs that pop up, with their text"
            isChecked = prefs.dialogs
            setOnCheckedChangeListener { _, on -> prefs.dialogs = on }
        })

        col.addView(text("Recordings", 16f, bold = true), margins(top = 20))
        col.addView(text("Share a recording to your PC, unzip it into Telestep's recordings folder and open it with " +
            "Review there to edit it and export Word, PDF, HTML or the narrated player.", 13f, gray = true))
        list = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        col.addView(list)
        setContentView(ScrollView(this).apply { addView(col) })
    }

    override fun onResume() {
        super.onResume()
        RecorderService.listeners.add(onServiceChange)
        refresh()
    }

    override fun onPause() {
        RecorderService.listeners.remove(onServiceChange)
        super.onPause()
    }

    private fun refresh() {
        val svc = RecorderService.instance
        status.text = when {
            svc == null -> "Telestep is off. Turn it on in Accessibility settings to record."
            svc.recording && svc.paused -> "Recording is paused."
            svc.recording -> "Recording… ${svc.session?.steps?.size ?: 0} steps so far."
            else -> "Ready. Start a recording here or with the floating button."
        }
        val on = svc != null
        btnService.visibility = if (on) View.GONE else View.VISIBLE
        btnRecord.isEnabled = on
        btnRecord.text = if (svc?.recording == true) "Stop recording" else "Start recording"
        btnButton.visibility = if (on) View.VISIBLE else View.GONE
        btnButton.isEnabled = svc?.recording != true
        btnButton.text = if (svc?.buttonShown == true) "Hide floating button" else "Show floating button"
        btnOff.visibility = if (on) View.VISIBLE else View.GONE
        showRecordings()
    }

    private fun showRecordings() {
        list.removeAllViews()
        val items = Recordings.list(this)
        if (items.isEmpty()) {
            list.addView(text("No recordings yet.", 14f, gray = true))
            return
        }
        val running = RecorderService.instance?.session?.dir
        for (r in items) {
            val row = LinearLayout(this).apply {
                orientation = LinearLayout.HORIZONTAL
                setPadding(0, dp(6), 0, dp(6))
            }
            val label = "${r.dir.name}\n${r.steps} steps" + if (r.dir == running) " (recording)" else ""
            row.addView(text(label, 14f), LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
            row.addView(Button(this).apply {
                text = "Share"
                isEnabled = r.dir != running
                setOnClickListener { share(r) }
            })
            row.addView(Button(this).apply {
                text = "Delete"
                isEnabled = r.dir != running
                setOnClickListener { confirmDelete(r) }
            })
            list.addView(row)
        }
    }

    private fun share(r: Recording) {
        Toast.makeText(this, "Packing the recording…", Toast.LENGTH_SHORT).show()
        Thread {
            val intent = try {
                Recordings.shareIntent(this, r)
            } catch (e: Exception) {
                null
            }
            runOnUiThread {
                if (intent != null) startActivity(intent)
                else Toast.makeText(this, "Could not pack the recording.", Toast.LENGTH_LONG).show()
            }
        }.start()
    }

    private fun confirmDelete(r: Recording) {
        AlertDialog.Builder(this)
            .setMessage("Delete recording ${r.dir.name} and its screenshots? This can't be undone.")
            .setPositiveButton("Delete") { _, _ ->
                Recordings.delete(r)
                refresh()
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    // ---- small view helpers
    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    private fun text(s: String, size: Float, bold: Boolean = false, gray: Boolean = false) = TextView(this).apply {
        text = s
        textSize = size
        if (bold) setTypeface(typeface, Typeface.BOLD)
        if (gray) setTextColor(0xFF666666.toInt())
    }

    private fun margins(top: Int = 0) = LinearLayout.LayoutParams(
        LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT,
    ).apply { topMargin = dp(top) }
}
