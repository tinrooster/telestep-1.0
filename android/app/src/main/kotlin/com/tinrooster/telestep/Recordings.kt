package com.tinrooster.telestep

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import com.tinrooster.telestep.core.Export
import com.tinrooster.telestep.core.RECORDER_VERSION
import org.json.JSONObject
import java.io.File
import java.time.LocalDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

/** User choices, kept in SharedPreferences. */
class Prefs private constructor(context: Context) {
    private val sp = context.getSharedPreferences("settings", Context.MODE_PRIVATE)

    var keyMode: String  // off | count | text (passwords are never recorded in any mode)
        get() = sp.getString("key_mode", "count") ?: "count"
        set(v) = sp.edit().putString("key_mode", v).apply()
    var afterShot: Boolean  // also capture the screen just after each tap
        get() = sp.getBoolean("after_shot", true)
        set(v) = sp.edit().putBoolean("after_shot", v).apply()
    var dialogs: Boolean  // a dialog that pops up becomes a step with its text
        get() = sp.getBoolean("dialogs", true)
        set(v) = sp.edit().putBoolean("dialogs", v).apply()

    companion object {
        fun of(context: Context) = Prefs(context.applicationContext)
    }
}

/** A finished (or running) recording on the phone. */
class Recording(val dir: File, val steps: Int, val title: String)

object Recordings {
    /** Android/data/com.tinrooster.telestep/files/Telestep: no storage permission needed; removed with the app. */
    fun root(context: Context): File =
        File(context.getExternalFilesDir(null) ?: context.filesDir, "Telestep").also { it.mkdirs() }

    fun list(context: Context): List<Recording> =
        root(context).listFiles { f -> File(f, "session.json").exists() }.orEmpty()
            .sortedByDescending { it.name }
            .map { d ->
                try {
                    val json = JSONObject(File(d, "session.json").readText())
                    Recording(d, json.optJSONArray("steps")?.length() ?: 0, json.optString("title"))
                } catch (e: Exception) {
                    Recording(d, 0, "")
                }
            }

    fun delete(r: Recording) {
        r.dir.deleteRecursively()
    }

    /** Zip the recording into the cache and offer it to other apps (mail, Drive, Nearby Share...). */
    fun shareIntent(context: Context, r: Recording): Intent {
        val out = File(File(context.cacheDir, ShareProvider.DIR).also { it.mkdirs() }, "Telestep_${r.dir.name}.zip")
        Export.zip(r.dir, out)
        val uri = Uri.parse("content://${ShareProvider.AUTHORITY}/${out.name}")
        val send = Intent(Intent.ACTION_SEND).apply {
            type = "application/zip"
            putExtra(Intent.EXTRA_STREAM, uri)
            putExtra(Intent.EXTRA_SUBJECT, "Telestep recording ${r.dir.name}")
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        return Intent.createChooser(send, "Share recording")
    }

    fun deviceName(context: Context): String =
        android.provider.Settings.Global.getString(context.contentResolver, android.provider.Settings.Global.DEVICE_NAME)
            ?.takeIf { it.isNotBlank() } ?: Build.MODEL

    /** The machine summary the desktop shows as environment.txt / the report appendix. */
    fun environment(context: Context): Map<String, String> {
        val dm = context.resources.displayMetrics
        return linkedMapOf(
            "Recorded" to LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss")),
            "Computer" to deviceName(context),
            "Device" to "${Build.MANUFACTURER} ${Build.MODEL}".trim(),
            "Operating system" to "Android ${Build.VERSION.RELEASE} (API ${Build.VERSION.SDK_INT})",
            "Security patch" to Build.VERSION.SECURITY_PATCH,
            "Recorder" to "Telestep $RECORDER_VERSION",
            "Displays" to "1: ${dm.widthPixels}x${dm.heightPixels} at 0,0",
            "Locale" to Locale.getDefault().toString(),
            "Time zone" to ZoneId.systemDefault().id,
        ).filterValues { it.isNotBlank() }
    }
}
