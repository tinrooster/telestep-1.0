package com.tinrooster.telestep.core

/** Minimal JSON writer: the app only ever writes session.json, so no library is needed. */
object Json {
    fun write(value: Any?): String = StringBuilder().also { emit(it, value, 0) }.toString()

    private fun emit(sb: StringBuilder, v: Any?, depth: Int) {
        when (v) {
            null -> sb.append("null")
            is String -> quote(sb, v)
            is Boolean, is Int, is Long -> sb.append(v)
            is Float -> number(sb, v.toDouble())
            is Double -> number(sb, v)
            is Map<*, *> -> container(sb, v.entries.toList(), depth, '{', '}') { e ->
                quote(sb, e.key.toString())
                sb.append(": ")
                emit(sb, e.value, depth + 1)
            }
            is Iterable<*> -> container(sb, v.toList(), depth, '[', ']') { emit(sb, it, depth + 1) }
            is IntArray -> emit(sb, v.toList(), depth)
            is DoubleArray -> emit(sb, v.toList(), depth)
            else -> quote(sb, v.toString())
        }
    }

    private fun <T> container(sb: StringBuilder, items: List<T>, depth: Int, open: Char, close: Char, item: (T) -> Unit) {
        if (items.isEmpty()) {
            sb.append(open).append(close)
            return
        }
        sb.append(open)
        items.forEachIndexed { i, x ->
            sb.append(if (i == 0) "\n" else ",\n").append(" ".repeat(depth + 1))
            item(x)
        }
        sb.append('\n').append(" ".repeat(depth)).append(close)
    }

    private fun number(sb: StringBuilder, d: Double) {
        if (d.isNaN() || d.isInfinite()) sb.append("null") else sb.append(d)
    }

    private fun quote(sb: StringBuilder, s: String) {
        sb.append('"')
        for (c in s) {
            when (c) {
                '"' -> sb.append("\\\"")
                '\\' -> sb.append("\\\\")
                '\n' -> sb.append("\\n")
                '\r' -> sb.append("\\r")
                '\t' -> sb.append("\\t")
                else -> if (c < ' ') sb.append(String.format("\\u%04x", c.code)) else sb.append(c)
            }
        }
        sb.append('"')
    }
}
