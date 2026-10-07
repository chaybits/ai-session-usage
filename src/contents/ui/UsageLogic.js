.pragma library

// Pure logic of the widget (no Plasma, no i18n), kept here so tests/test_usage_logic.js can run it.

// A source read from a local file (Claude Code's status line) is read this often: it costs no request.
var LOCAL_POLL_MS = 30000
// A burst of clicks should not turn into a burst of requests.
var TAP_THROTTLE_MS = 10000
// The helper's 15 s timeout bounds each network step, not the whole run (DNS and a slow trickle escape it);
// this is what bounds the run.
var WATCHDOG_MS = 60000
// Rate-limited without a usable Retry-After: wait this long.
var DEFAULT_RETRY_S = 600
// One odd Retry-After must not idle the widget for hours (the helper clamps too).
var MAX_RETRY_S = 3600
// First retry after a network or server failure (login with no network yet); doubles up to the poll interval.
var FAST_RETRY_MS = 30000
// How much of a failed run's output is shown: the tail, where the reason is.
var OUTPUT_TAIL_CHARS = 160
// A reset time this far past still reads "resetting now" (the poll may be late); beyond it, it is stale.
var RESET_PAST_MS = 60000
// Within this of the reset time the countdown would show 0 minutes.
var RESET_NOW_MS = 30000
// A reset further ahead than this shows its date; nearer, its weekday (a weekday alone is ambiguous past a week).
var WEEKDAY_SPAN_DAYS = 6
// "Fit to width": at this width, in grid units, the content is at 100 % (about 400 px at the default font).
var BASE_WIDTH_UNITS = 22
// The height of the slot the widget was designed in (with BASE_WIDTH_UNITS, about 400 x 256): what a widget just
// added asks the desktop for.
var BASE_HEIGHT_UNITS = 14
// Zoom bounds, so a tiny or huge widget stays legible and laid out.
var MIN_ZOOM = 0.5
var MAX_ZOOM = 4
// "Shrink to fit" never goes below this share of the zoom: past it, text is unreadable and scrolling is better.
var MIN_SHRINK = 0.4
// Shrink to fit aims this far under the height, and grows back only below GROW_ROOM of it (hysteresis).
var FIT_TARGET = 0.98
var GROW_ROOM = 0.95
// The panel (compact) form shows this many rows per provider (session and weekly); the tooltip lists every row.
var COMPACT_ROWS = 2
// The providers in their default display order (main.qml lists them in this order too).
var PROVIDER_ORDER = ["claude", "codex"]

// The plugin's file path from its resolved URL (undoes the escaping of # % ? and the like).
function scriptPath(url) {
    return decodeURIComponent(String(url).replace(/^file:\/\//, ""))
}

// The helper prints one JSON line; anything else is shown as a badoutput error with the output's tail.
// Valid JSON that is not the helper's shape (null, a number, ok without rows) is badoutput too: the widget
// reads result.ok and result.rows without further checks.
function parseOutput(stdout, stderr) {
    try {
        const lines = stdout.trim().split("\n")
        const result = JSON.parse(lines[lines.length - 1])
        if (result === null || typeof result !== "object" || typeof result.ok !== "boolean"
                || (result.ok && !Array.isArray(result.rows))) {
            throw new TypeError("not the helper's result shape")
        }
        return result
    } catch (e) {
        return { ok: false, error: "badoutput", message: (stderr || stdout).trim().slice(-OUTPUT_TAIL_CHARS) }
    }
}

// When to poll next after this result. prevStep is the last fast-retry step in ms (0 = none).
// Returns { intervalMs, step }.
function nextPoll(result, prevStep, pollMs) {
    if (result.ok) {
        return { intervalMs: pollMs, step: 0 }
    }
    if (result.error === "ratelimited") {
        // 0 is a real answer ("retry now"; the helper clamps a past date to 0), not a missing one.
        const retryS = Math.min(typeof result.retry_after === "number" ? result.retry_after : DEFAULT_RETRY_S, MAX_RETRY_S)
        return { intervalMs: Math.max(pollMs, retryS * 1000), step: 0 }
    }
    if (result.error === "network" || (result.error === "http" && result.status >= 500)) {
        const step = Math.min(prevStep > 0 ? prevStep * 2 : FAST_RETRY_MS, pollMs)
        return { intervalMs: step, step: step }
    }
    return { intervalMs: pollMs, step: 0 }
}

// Classify a reset time against now: { kind: "none" | "now" | "past" | "future", mins }.
function resetInfo(iso, nowMs) {
    if (!iso) {
        return { kind: "none", mins: 0 }
    }
    const t = Date.parse(iso)
    if (isNaN(t)) {
        return { kind: "none", mins: 0 }
    }
    const diff = t - nowMs
    if (diff < -RESET_PAST_MS) {
        return { kind: "past", mins: 0 }
    }
    if (diff < RESET_NOW_MS) {
        return { kind: "now", mins: 0 }
    }
    return { kind: "future", mins: Math.round(diff / 60000) }
}

// How a reset time is written: "time" (session rows), "weekday" (within a week) or "date" (further).
function resetStyle(withDay, mins) {
    if (!withDay) {
        return "time"
    }
    return mins > WEEKDAY_SPAN_DAYS * 1440 ? "date" : "weekday"
}

// The rows of one provider minus the ones hidden in the settings (ids like "claude:weekly_scoped:Fable").
function visibleRows(rows, hiddenIds) {
    if (!rows) {
        return []
    }
    const hidden = hiddenIds || []
    return rows.filter(r => hidden.indexOf(r.id) < 0)
}

// True when the last good answer is older than the user's threshold (0 minutes = never).
function isOutdated(lastSuccessMs, nowMs, staleMinutes) {
    return staleMinutes > 0 && lastSuccessMs > 0 && nowMs - lastSuccessMs > staleMinutes * 60000
}

// "normal", "warning" or "critical" for a used percentage; a threshold of 0 is off.
function levelOf(percent, warnAt, criticalAt) {
    if (criticalAt > 0 && percent >= criticalAt) {
        return "critical"
    }
    if (warnAt > 0 && percent >= warnAt) {
        return "warning"
    }
    return "normal"
}

// The colour of a level: `colors` = { normal, warning, critical }.
function levelColor(level, colors) {
    return level === "critical" ? colors.critical : level === "warning" ? colors.warning : colors.normal
}

// The content's zoom: from the widget's width ("fit") or the user's percentage ("fixed"), within bounds.
function zoomFor(sizeMode, width, baseWidth, percent) {
    const z = sizeMode === "fixed" ? percent / 100 : (baseWidth > 0 ? width / baseWidth : 1)
    return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, isFinite(z) && z > 0 ? z : 1))
}

// The size to ask the desktop for, in one dimension: the design size for a widget not yet placed (current 0),
// then never more than the size it has. The desktop grows a widget's slot whenever its preferred size rises
// above the slot, and never shrinks it back (plasma-workspace, gridlayoutmanager.cpp, adjustToItemSizeHints),
// so asking for more than the current size would undo the size the user gave it.
function preferredSize(design, current) {
    return current > 0 ? Math.min(design, current) : design
}

// A widget first shown on a desktop asks for its design size this long after it appears. The desktop grows a
// widget only when a request changes after it has been placed, so the request must come after placement.
var ASK_DESIGN_AFTER_MS = 200
// ...and keeps asking for this long before it asks for no more than it has: the desktop answers a request on a
// zero-interval timer, so it has long grown the widget by then.
var PLACED_AFTER_MS = 1000

// "Shrink to fit": the next content scale k (MIN_SHRINK..ceiling) from the current k and the measured heights.
// Content height is only roughly proportional to the scale: fixed paddings, and line heights in whole pixels,
// which at small sizes move the height in steps of several pixels. So it aims FIT_TARGET under the viewport,
// shrinks again while still over, grows back only with more than GROW_ROOM to spare, and never grows to
// `ceiling`, the smallest scale already seen overflowing at this size (the caller keeps it); without that
// cap a step larger than the GROW_ROOM band would make the fit hop across it forever.
function shrinkStep(k, viewportHeight, contentHeight, ceiling) {
    const top = Math.min(1, typeof ceiling === "number" ? ceiling : 1)
    if (!(viewportHeight > 0) || !(contentHeight > 0)) {
        return k
    }
    if (contentHeight > viewportHeight) {
        return Math.max(MIN_SHRINK, k * viewportHeight * FIT_TARGET / contentHeight)
    }
    if (k < top && contentHeight < viewportHeight * GROW_ROOM) {
        return Math.min(top, k * viewportHeight * FIT_TARGET / contentHeight)
    }
    return k
}

// The rows seen so far, for the settings page: [{ id, provider, label }] in first-seen order, labels kept
// current. Returns the new JSON text, or null when nothing changed (so the config is not rewritten).
function mergeKnownRows(knownJson, rows) {
    const known = parseKnownRows(knownJson)
    let changed = false
    for (const r of rows || []) {
        const entry = { id: r.id, provider: r.provider, label: r.label }
        const i = known.findIndex(k => k.id === r.id)
        if (i < 0) {
            known.push(entry)
            changed = true
        } else if (known[i].label !== r.label || known[i].provider !== r.provider) {
            known[i] = entry
            changed = true
        }
    }
    return changed ? JSON.stringify(known) : null
}

// The stored list of seen rows; a damaged value is a cache, so it restarts empty (rows reappear on the next answer).
function parseKnownRows(knownJson) {
    let known
    try {
        known = JSON.parse(knownJson || "[]")
    } catch (e) {
        return []
    }
    return Array.isArray(known) ? known.filter(k => k && typeof k.id === "string") : []
}

// `items` in the user's order. They arrive in the default order (providers in display order, each provider's
// rows in the server's order); the ones whose id is in `order` come first, in its order, and the rest follow
// in the default order, so a row seen for the first time goes to the end. `idOf` reads an item's id.
function applyOrder(items, order, idOf) {
    const rank = {}
    ;(order || []).forEach((id, i) => {
        if (!(id in rank)) {
            rank[id] = i
        }
    })
    const placed = (items || []).filter(it => idOf(it) in rank).sort((a, b) => rank[idOf(a)] - rank[idOf(b)])
    return placed.concat((items || []).filter(it => !(idOf(it) in rank)))
}

// How the card lays out the rows. `sectionRows` = per provider, in display order, its visible rows in the
// server's order; `order` = the user's row ids. Returns { mixed, blocks: [{ section, rows: [{ section, row }] }] }.
// While each provider's rows stay together there is one block per provider, in the order of its first row; a
// provider with no rows (it shows only its status line) keeps the place it has by default. Once the order mixes
// providers there is one block of every row (section -1), and the card names the provider in each row.
function arrangeRows(sectionRows, order) {
    const flat = []
    const start = []
    ;(sectionRows || []).forEach((rows, section) => {
        start.push(flat.length)
        ;(rows || []).forEach(row => flat.push({ section: section, row: row }))
    })
    const ordered = applyOrder(flat, order, e => e.row.id)
    const firstAt = {}
    let mixed = false
    ordered.forEach((e, i) => {
        if (!(e.section in firstAt)) {
            firstAt[e.section] = i
        } else if (ordered[i - 1].section !== e.section) {
            mixed = true
        }
    })
    if (mixed) {
        return { mixed: true, blocks: [{ section: -1, rows: ordered }] }
    }
    // A provider with rows sorts by its first row's place; one without, just before where its rows would start.
    const key = section => section in firstAt ? firstAt[section] : start[section] - 0.5
    const blocks = start.map((s, section) => ({ section: section, rows: ordered.filter(e => e.section === section) }))
    return { mixed: false, blocks: blocks.sort((a, b) => key(a.section) - key(b.section)) }
}

// The arranged rows grouped by provider, providers in the order of their first row: [{ section, rows }].
function rowsByProvider(arranged) {
    const groups = []
    for (const block of arranged.blocks) {
        for (const e of block.rows) {
            let group = groups.find(g => g.section === e.section)
            if (!group) {
                group = { section: e.section, rows: [] }
                groups.push(group)
            }
            group.rows.push(e.row)
        }
    }
    return groups
}

// The rows of the settings page in their default order: providers in display order, each provider's rows in
// the order they were first seen (the server's order at the time); `known` = [{ id, provider, label }].
function defaultKnownOrder(known) {
    const rank = p => {
        const i = PROVIDER_ORDER.indexOf(p)
        return i < 0 ? PROVIDER_ORDER.length : i
    }
    return (known || []).map((k, i) => ({ k: k, i: i }))
        .sort((a, b) => rank(a.k.provider) - rank(b.k.provider) || a.i - b.i)
        .map(x => x.k)
}

// `ids` with the one at `index` moved by `delta` places; null when that would leave the list.
function moveId(ids, index, delta) {
    const target = index + delta
    if (index < 0 || index >= ids.length || target < 0 || target >= ids.length) {
        return null
    }
    const out = ids.slice()
    const moved = out.splice(index, 1)[0]
    out.splice(target, 0, moved)
    return out
}

// What the panel (compact) form shows: per provider, its first visible rows' percentages, a dot between
// rows of one provider and a bar between providers. groups: [{ rows }] in display order.
function compactParts(groups) {
    const parts = []
    for (const g of groups || []) {
        const rows = (g.rows || []).slice(0, COMPACT_ROWS)
        if (rows.length === 0) {
            continue
        }
        if (parts.length > 0) {
            parts.push({ kind: "gap", text: "|", percent: 0 })
        }
        rows.forEach((r, i) => {
            if (i > 0) {
                parts.push({ kind: "sep", text: "·", percent: 0 })
            }
            parts.push({ kind: "value", text: Math.round(r.percent) + "%", percent: r.percent })
        })
    }
    return parts.length > 0 ? parts : [{ kind: "none", text: "--", percent: 0 }]
}

// The compact form as one string (its tooltip and the tests).
function compactText(groups) {
    return compactParts(groups).map(p => p.text).join(" ")
}
