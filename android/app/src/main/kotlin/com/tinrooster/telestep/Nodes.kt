package com.tinrooster.telestep

import android.graphics.Rect
import android.view.accessibility.AccessibilityNodeInfo
import com.tinrooster.telestep.core.UiNode

/** An AccessibilityNodeInfo seen through the core's UiNode, so naming and captions stay in the tested core. */
class NodeAdapter(val node: AccessibilityNodeInfo) : UiNode {
    override val text get() = node.text?.toString()
    override val description get() = node.contentDescription?.toString()
    override val hint get() = node.hintText?.toString()
    override val className get() = node.className?.toString()
    override val isCheckable get() = node.isCheckable
    override val isEditable get() = node.isEditable
    override val isPassword get() = node.isPassword
    override val isListItem get() = node.collectionItemInfo != null
    override val isHeading get() = node.isHeading
    override val bounds: IntArray
        get() = Rect().also { node.getBoundsInScreen(it) }.let { intArrayOf(it.left, it.top, it.right, it.bottom) }

    override fun parent(): UiNode? = node.parent?.let { NodeAdapter(it) }

    override fun children(): List<UiNode> = (0 until node.childCount).mapNotNull { i -> node.getChild(i)?.let { NodeAdapter(it) } }
}

/** Screen rectangles of every password field in the given window roots (blurred in screenshots). */
fun passwordRects(roots: List<AccessibilityNodeInfo>, limit: Int = 400): List<Rect> {
    val out = mutableListOf<Rect>()
    var seen = 0
    fun walk(n: AccessibilityNodeInfo, depth: Int) {
        if (depth > 40 || seen++ > limit) return
        if (n.isPassword) out.add(Rect().also { n.getBoundsInScreen(it) })
        for (i in 0 until n.childCount) n.getChild(i)?.let { walk(it, depth + 1) }
    }
    roots.forEach { walk(it, 0) }
    return out
}
