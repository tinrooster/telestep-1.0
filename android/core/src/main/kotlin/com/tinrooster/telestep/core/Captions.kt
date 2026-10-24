package com.tinrooster.telestep.core

/** (friendly, technical) captions, worded like the desktop's (telestep_model.click_texts) but for touch. */
object Captions {
    private fun q(s: String) = "\"$s\""

    fun tap(t: Target, x: Int, y: Int, longPress: Boolean = false): Pair<String, String> {
        val tv = if (longPress) "Long press" else "Tap"
        val (name, kind, inh) = Triple(t.name, t.kind, t.inherited)
        val tech = when {
            name.isNotEmpty() && kind.isNotEmpty() && inh -> "$tv in ${q(name)} ($kind)"
            name.isNotEmpty() && kind.isNotEmpty() -> "$tv on ${q(name)} ($kind)"
            name.isNotEmpty() -> "$tv on ${q(name)}"
            kind.isNotEmpty() -> "$tv on $kind"
            else -> "$tv at ($x, $y)"
        }
        val verb = if (longPress) "Long-press" else "Tap"
        if (name.isEmpty()) {
            val what = if (kind.isNotEmpty()) "the ${kind.lowercase()}" else "the screen"
            return "$verb on $what" to tech
        }
        val qn = q(name)
        if (inh) return "$verb in $qn" to tech
        val tap = !longPress
        val friendly = when (kind) {
            "Button" -> "$verb the $qn button"
            "TabItem" -> "$verb the $qn tab"
            "CheckBox" -> "$verb the $qn checkbox"
            "Switch" -> "$verb the $qn switch"
            "RadioButton" -> if (tap) "Select the $qn option" else "$verb the $qn option"
            "Edit" -> "$verb in the $qn text box"
            "ComboBox" -> "$verb the $qn drop-down"
            "ListItem" -> if (tap) "Select $qn" else "$verb $qn"
            "Image" -> "$verb the $qn image"
            else -> "$verb $qn"
        }
        return friendly to tech
    }

    fun scroll(direction: String, name: String): Pair<String, String> {
        val f = "Scroll $direction" + if (name.isNotEmpty()) " in ${q(name)}" else ""
        return f to f
    }

    /** mode: "count" (how many characters) or "text" (what was typed).  Passwords are never written. */
    fun type(mode: String, text: String, count: Int, password: Boolean): Pair<String, String> = when {
        password -> "Type your password" to "Typed text in a password field ($count characters, hidden)"
        mode == "text" -> "Type ${q(text)}" to "Typed text: $text"
        else -> "Type some text ($count characters)" to "Typed text ($count characters)"
    }

    fun dialog(title: String): Pair<String, String> =
        "A dialog appeared: ${q(title)}" to "Dialog window ${q(title)}"
}
