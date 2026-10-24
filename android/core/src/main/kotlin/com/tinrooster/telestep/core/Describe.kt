package com.tinrooster.telestep.core

/** What the app layer exposes of one on-screen element (wraps AccessibilityNodeInfo; plain data in tests). */
interface UiNode {
    val text: String?
    val description: String?
    val hint: String?
    val className: String?
    val isCheckable: Boolean
    val isEditable: Boolean
    val isPassword: Boolean
    val isListItem: Boolean  // a row of a list / grid (has collection item info)
    val isHeading: Boolean
    val bounds: IntArray  // l, t, r, b in screen pixels
    fun parent(): UiNode?
    fun children(): List<UiNode>
}

/** The element a step is about: what the captions say and what the marker outlines. */
data class Target(
    val name: String,
    val kind: String,  // desktop control kinds: Button, Edit, CheckBox, ListItem, ...
    val inherited: Boolean,  // name taken from a parent (caption says "Tap in ...")
    val bounds: IntArray?,
    val password: Boolean,
)

object Describe {
    private const val MAX_NAME = 80

    /** Android widget class -> the control kind the desktop captions know.  Unknown classes give "". */
    fun kind(node: UiNode): String {
        val cls = node.className.orEmpty()
        val short = cls.substringAfterLast('.')
        return when {
            node.isEditable || short.endsWith("EditText") || short == "AutoCompleteTextView" -> "Edit"
            short.contains("Switch") || short == "ToggleButton" -> "Switch"
            short.endsWith("CheckBox") || short == "CheckedTextView" -> "CheckBox"
            short.endsWith("RadioButton") -> "RadioButton"
            short.endsWith("Button") || short == "FloatingActionButton" || short == "Chip" -> "Button"
            short == "Spinner" -> "ComboBox"
            short.endsWith("Tab") || short == "TabView" -> "TabItem"
            node.isListItem -> "ListItem"
            short.endsWith("ImageView") -> "Image"
            short.endsWith("TextView") -> "Text"
            short == "WebView" -> "Document"
            node.isCheckable -> "CheckBox"
            short.endsWith("Layout") || short == "ViewGroup" || short.endsWith("RecyclerView")
                || short == "ListView" || short == "ScrollView" -> "Group"
            else -> ""
        }
    }

    fun ownName(node: UiNode): String {
        val raw = sequenceOf(node.text, node.description, if (node.isEditable) node.hint else null)
            .firstOrNull { !it.isNullOrBlank() }
        return clean(raw)
    }

    /**
     * Name for the element: its own text or description; else the first text inside it (a clickable row whose label
     * is a child TextView, the usual Android layout); else the nearest named parent (marked inherited).
     */
    fun target(node: UiNode): Target {
        val kind = kind(node)
        var name = if (node.isPassword) clean(node.hint ?: node.description) else ownName(node)
        var inherited = false
        if (name.isEmpty() && !node.isPassword) name = childText(node, 3)
        if (name.isEmpty()) {
            var p = node.parent()
            var hops = 0
            while (p != null && hops < 4) {
                val pn = ownName(p)
                if (pn.isNotEmpty()) {
                    name = pn
                    inherited = true
                    break
                }
                p = p.parent()
                hops++
            }
        }
        return Target(name, kind, inherited, node.bounds.takeIf { it.size == 4 }, node.isPassword)
    }

    private fun childText(node: UiNode, depth: Int): String {
        if (depth == 0) return ""
        for (c in node.children()) {
            if (c.isPassword) continue
            val n = ownName(c)
            if (n.isNotEmpty()) return n
            val deeper = childText(c, depth - 1)
            if (deeper.isNotEmpty()) return deeper
        }
        return ""
    }

    /** Visible texts of a dialog, in screen order, for the step's dialog text. */
    fun texts(root: UiNode, limit: Int = 30): List<String> {
        val out = mutableListOf<String>()
        fun walk(n: UiNode, depth: Int) {
            if (depth > 8 || out.size >= limit) return
            val k = kind(n)
            val t = if (n.isPassword || k == "Edit") "" else clean(n.text)
            if (t.isNotEmpty() && k != "Button" && t !in out) out.add(t)
            n.children().forEach { walk(it, depth + 1) }
        }
        walk(root, 0)
        return out
    }

    fun clean(s: CharSequence?): String =
        s?.toString()?.replace(Regex("\\s+"), " ")?.trim()?.take(MAX_NAME).orEmpty()
}
