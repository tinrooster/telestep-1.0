package com.tinrooster.telestep.core

import java.io.File
import java.nio.file.Files
import java.time.LocalTime
import java.util.zip.ZipFile
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class FakeNode(
    override val className: String? = "android.view.View",
    override val text: String? = null,
    override val description: String? = null,
    override val hint: String? = null,
    override val isCheckable: Boolean = false,
    override val isEditable: Boolean = false,
    override val isPassword: Boolean = false,
    override val isListItem: Boolean = false,
    override val isHeading: Boolean = false,
    override val bounds: IntArray = intArrayOf(10, 20, 110, 70),
    val kids: List<FakeNode> = emptyList(),
) : UiNode {
    var up: FakeNode? = null

    init {
        kids.forEach { it.up = this }
    }

    override fun parent() = up
    override fun children() = kids
}

class CoreTest {
    @Test
    fun kinds() {
        assertEquals("Button", Describe.kind(FakeNode("android.widget.Button")))
        assertEquals("Button", Describe.kind(FakeNode("com.google.android.material.button.MaterialButton")))
        assertEquals("Edit", Describe.kind(FakeNode("android.widget.EditText")))
        assertEquals("Switch", Describe.kind(FakeNode("androidx.appcompat.widget.SwitchCompat")))
        assertEquals("CheckBox", Describe.kind(FakeNode("android.widget.CheckBox")))
        assertEquals("ListItem", Describe.kind(FakeNode("android.widget.LinearLayout", isListItem = true)))
        assertEquals("Group", Describe.kind(FakeNode("android.widget.FrameLayout")))
        assertEquals("", Describe.kind(FakeNode("android.view.View")))
    }

    @Test
    fun namesFromSelfChildrenAndParent() {
        assertEquals("Save", Describe.target(FakeNode("android.widget.Button", text = "  Save\n")).name)
        assertEquals("Search", Describe.target(FakeNode("android.widget.ImageButton", description = "Search")).name)
        val row = FakeNode("android.widget.LinearLayout", isListItem = true,
            kids = listOf(FakeNode("android.widget.ImageView"), FakeNode("android.widget.TextView", text = "Wi-Fi")))
        val t = Describe.target(row)
        assertEquals("Wi-Fi" to "ListItem", t.name to t.kind)
        assertFalse(t.inherited)
        val icon = FakeNode("android.view.View")
        FakeNode("android.widget.FrameLayout", description = "Toolbar", kids = listOf(icon))
        val ti = Describe.target(icon)
        assertEquals("Toolbar", ti.name)
        assertTrue(ti.inherited)
        assertEquals("Email", Describe.target(FakeNode("android.widget.EditText", hint = "Email", isEditable = true)).name)
    }

    @Test
    fun passwordFieldNeverNamedByItsText() {
        val pw = FakeNode("android.widget.EditText", text = "hunter2", hint = "Password", isEditable = true, isPassword = true)
        val t = Describe.target(pw)
        assertEquals("Password", t.name)
        assertTrue(t.password)
        val form = FakeNode("android.widget.LinearLayout", kids = listOf(FakeNode("android.widget.TextView", text = "Sign in"), pw))
        assertFalse("hunter2" in Describe.texts(form))
    }

    @Test
    fun captionsMatchDesktopStyle() {
        val save = Target("Save", "Button", false, null, false)
        assertEquals("Tap the \"Save\" button" to "Tap on \"Save\" (Button)", Captions.tap(save, 1, 2))
        assertEquals("Long-press the \"Save\" button", Captions.tap(save, 1, 2, longPress = true).first)
        assertEquals("Select \"Wi-Fi\"", Captions.tap(Target("Wi-Fi", "ListItem", false, null, false), 0, 0).first)
        assertEquals("Tap on the screen" to "Tap at (5, 6)", Captions.tap(Target("", "", false, null, false), 5, 6))
        assertEquals("Tap in \"Toolbar\"", Captions.tap(Target("Toolbar", "Group", true, null, false), 0, 0).first)
        assertEquals("Type your password", Captions.type("text", "", 7, true).first)
        assertEquals("Type \"hello\"", Captions.type("text", "hello", 5, false).first)
        assertEquals("Type some text (5 characters)", Captions.type("count", "hello", 5, false).first)
    }

    @Test
    fun recorderWritesDesktopSession() {
        val dir = Files.createTempDirectory("ts").toFile().resolve(Session.dirName())
        val s = Session(dir, host = "Pixel 8", environment = mapOf("Device" to "Google Pixel 8"))
        s.makeDirs()
        val rec = StepRecorder(s, "count") { LocalTime.of(14, 5, 9) }
        val jpeg = byteArrayOf(-1, -40, -1, -39)  // a placeholder; the desktop test uses a real picture
        val place = Place("Settings", "14", "Network & internet")
        val st = rec.tap(Target("Wi-Fi", "ListItem", false, intArrayOf(0, 200, 1080, 320), false), 540, 260, place,
            Frame(jpeg, 0.5))
        rec.after(st, Frame(jpeg, 0.5))
        assertEquals(listOf(270.0, 130.0), st.marker!!["pt"])
        assertEquals(listOf(0.0, 100.0, 540.0, 160.0), st.marker!!["rect"])
        assertTrue(File(dir, "raw/${st.id}.jpg").exists() && File(dir, "raw/${st.id}_after.jpg").exists())

        val list = Target("Networks", "Group", false, null, false)
        assertTrue(rec.scroll(list, "down", 500, 900, place, Frame(jpeg, 0.5), 1000) != null)
        assertNull(rec.scroll(list, "down", 500, 900, place, Frame(jpeg, 0.5), 2000), "continued scroll merges")
        assertTrue(rec.scroll(list, "up", 500, 900, place, Frame(jpeg, 0.5), 2500) != null, "new direction is a new step")

        val field = Target("Search", "Edit", false, null, false)
        assertTrue(rec.text("f1", field, "h", place) != null)
        assertNull(rec.text("f1", field, "hello", place))
        assertEquals("Type some text (5 characters)", s.steps.last().friendly)
        rec.dialog("Forget network?", listOf("Forget network?", "Saved password will be removed"), place, null)

        val json = File(dir, "session.json").readText()
        assertTrue("\"format\": 2" in json && "\"when\": \"14:05:09\"" in json && "\"app_version\": \"14\"" in json)
        assertEquals(listOf("click", "scroll", "scroll", "type", "dialog"), s.steps.map { it.kind })

        val zip = File(dir.parentFile, "out.zip")
        Export.zip(dir, zip)
        ZipFile(zip).use { z ->
            val names = z.entries().toList().map { it.name }
            assertTrue("${dir.name}/session.json" in names && "${dir.name}/raw/${st.id}.jpg" in names, names.toString())
        }

        System.getProperty("telestep.sampleOut")?.let { out ->  // the desktop cross-check reads this session
            dir.copyRecursively(File(out), overwrite = true)
        }
    }

    @Test
    fun keyModeOffRecordsNoTyping() {
        val s = Session(Files.createTempDirectory("ts").toFile())
        val rec = StepRecorder(s, "off")
        assertNull(rec.text("f", Target("Search", "Edit", false, null, false), "abc", Place()))
        assertTrue(s.steps.isEmpty())
    }

    @Test
    fun jsonEscapes() {
        assertEquals("{\n \"a\": \"q\\\"\\n\\u0001\",\n \"b\": [\n  1,\n  2.5,\n  null\n ]\n}",
            Json.write(linkedMapOf("a" to "q\"\n\u0001", "b" to listOf(1, 2.5, null))))
    }
}
