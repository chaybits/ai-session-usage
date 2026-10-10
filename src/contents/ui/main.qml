import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.plasma.plasmoid
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.components as PlasmaComponents3
import org.kde.kirigami as Kirigami
import "UsageLogic.js" as Logic

// AI Session Usage: the subscription limits of Claude Code (session, weekly, per-model weekly) and of ChatGPT's
// Codex (its plan's windows), in the servers' order, each polled every few minutes by
// contents/code/fetch_usage.py. Click anywhere to refresh. Each CLI is asked for its own usage, with its own
// login, over its own protocol (Claude Code headless, or its status line; Codex's app server): the widget
// reads no login and talks to no server (docs/ARCHITECTURE.md D16, D18, D20).
PlasmoidItem {
    id: root

    readonly property string scriptPath: Logic.scriptPath(Qt.resolvedUrl("../code/fetch_usage.py"))
    readonly property int pollMs: Math.max(1, Plasmoid.configuration.refreshMinutes) * 60000
    property double nowMs: Date.now()
    readonly property var hiddenRows: Plasmoid.configuration.hiddenRows || []
    readonly property int staleMinutes: Plasmoid.configuration.staleMinutes
    readonly property color staleColor: Plasmoid.configuration.staleColor
    // The colours of the two thresholds (by default orange and red; outdated numbers are yellow).
    readonly property color warnColor: Plasmoid.configuration.warnColor
    readonly property color criticalColor: Plasmoid.configuration.criticalColor
    // The providers this widget can show, in display order; the settings turn each on or off.
    readonly property var providers: [
        { id: "claude", name: i18n("Claude"), cli: i18n("Claude Code"), show: Plasmoid.configuration.showClaude,
          path: Plasmoid.configuration.credentialsPath,
          // a stored "endpoint" (a source removed on 2026-10-08, D18) is read as the default
          source: Plasmoid.configuration.claudeSource === "statusline" ? "statusline" : "claudecode",
          program: Plasmoid.configuration.claudeCommand },
        { id: "codex", name: i18n("ChatGPT"), cli: i18n("Codex"), show: Plasmoid.configuration.showCodex,
          path: Plasmoid.configuration.codexAuthPath, program: Plasmoid.configuration.codexCommand }
    ].filter(p => p.show)
    // The UsageSource objects, one per enabled provider, in display order.
    property var sources: []
    // A section per provider with something to show (data, an error, or a first fetch still running). A
    // provider with no login at all that never answered is left out, so a Claude-only user sees no
    // ChatGPT section; when that leaves nothing, noLoginText says so instead.
    readonly property var sections: sources
        .filter(s => !(s.errorKind === "nologin" && s.lastSuccessMs === 0))
        .map(s => ({ source: s, rows: Logic.visibleRows(s.usage ? s.usage.rows : null, hiddenRows) }))
    readonly property bool anyBusy: sources.some(s => s.busy)
    // The rows in the user's order (Settings, Rows): per provider, or one list once the order mixes providers.
    readonly property var rowOrder: Plasmoid.configuration.rowOrder || []
    readonly property var layout: Logic.arrangeRows(sections.map(sec => sec.rows), rowOrder)

    // A desktop widget always shows the full card; in a panel it is a short text with a popup.
    preferredRepresentation: Plasmoid.formFactor === PlasmaCore.Types.Planar ? fullRepresentation : null
    Plasmoid.backgroundHints: PlasmaCore.Types.DefaultBackground | PlasmaCore.Types.ConfigurableBackground
    toolTipMainText: titleText()
    toolTipSubText: layout.blocks.map(b => b.rows.map(e => tooltipEntry(e)).join(" · ")).filter(t => t).join(" · ")

    Plasmoid.contextualActions: [
        PlasmaCore.Action {
            text: i18n("Refresh now")
            icon.name: "view-refresh"
            onTriggered: root.refreshAll(true)
        }
    ]

    Instantiator {
        id: instantiator
        model: root.providers
        delegate: UsageSource {
            required property var modelData
            providerId: modelData.id
            providerName: modelData.name
            cliName: modelData.cli
            credentialsPath: modelData.path
            dataSource: modelData.source || ""
            program: modelData.program || ""
            programOption: modelData.id === "claude" ? "--claude" : "--codex"
            scriptPath: root.scriptPath
            // a local file costs no request, so it is read often; Claude Code and Codex are started at the user's
            // interval
            pollMs: dataSource === "statusline" ? Math.min(root.pollMs, Logic.LOCAL_POLL_MS) : root.pollMs
            onAnswered: result => root.recordRows(result)
        }
        onObjectAdded: root.collectSources()
        onObjectRemoved: root.collectSources()
    }

    // Countdowns and the outdated colour move between polls without another request.
    Timer {
        interval: 30000
        repeat: true
        running: true
        onTriggered: root.nowMs = Date.now()
    }

    function collectSources() {
        const list = []
        for (let i = 0; i < instantiator.count; i++) {
            if (instantiator.objectAt(i)) {
                list.push(instantiator.objectAt(i))
            }
        }
        sources = list
    }

    function refreshAll(manual) {
        for (const s of sources) {
            s.refresh(manual)
        }
    }

    // Remember every row ever shown, so the settings can offer it for hiding; written only on a change.
    function recordRows(result) {
        nowMs = Date.now()
        if (!result.ok) {
            return
        }
        const merged = Logic.mergeKnownRows(Plasmoid.configuration.knownRows, result.rows)
        if (merged !== null) {
            Plasmoid.configuration.knownRows = merged
        }
    }

    function isOutdated(source) {
        return Logic.isOutdated(source.lastSuccessMs, nowMs, staleMinutes)
    }

    // One row of the tooltip: its service (when more than one shows), its label and the number the card prints.
    function tooltipEntry(entry) {
        const pct = i18nc("a used percentage", "%1%", Logic.displayPercent(entry.row.percent))
        if (sections.length > 1) {
            return i18nc("a service's name, one of its usage rows, its percentage", "%1 %2 %3",
                         sections[entry.section].source.providerName, entry.row.label, pct)
        }
        return i18nc("a usage row, its percentage", "%1 %2", entry.row.label, pct)
    }

    function titleText() {
        return sections.length === 1 ? i18n("%1 usage", sections[0].source.providerName) : i18n("AI session usage")
    }

    function shortTime(ms) {
        return new Date(ms).toLocaleTimeString(Qt.locale(), Locale.ShortFormat)
    }

    function resetText(iso, withDay) {
        const info = Logic.resetInfo(iso, nowMs)
        if (info.kind === "none") {
            return ""
        }
        if (info.kind === "now") {
            return i18n("Resetting now")
        }
        // The locale's own formats (24-hour here, "2:04 PM" in a 12-hour locale), never a fixed pattern.
        const date = new Date(Date.parse(iso))
        const time = date.toLocaleTimeString(Qt.locale(), Locale.ShortFormat)
        const style = Logic.resetStyle(withDay, info.mins)
        const at = style === "date" ? date.toLocaleDateString(Qt.locale(), Locale.ShortFormat) + " " + time
            : style === "weekday" ? Qt.locale().dayName(date.getDay(), Locale.ShortFormat) + " " + time
            : time
        if (info.kind === "past") {
            return i18n("Reset at %1", at)
        }
        const mins = info.mins
        const d = Math.floor(mins / 1440)
        const h = Math.floor((mins % 1440) / 60)
        const m = mins % 60
        const span = d > 0 ? i18n("%1d %2h", d, h) : (h > 0 ? i18n("%1h %2m", h, m) : i18n("%1m", m))
        return i18n("Resets in %1 · %2", span, at)
    }

    // A provider's own line: empty when all is well (the footer covers it), else what went wrong.
    function sectionStatus(source) {
        const lastGood = source.lastSuccessMs > 0 ? shortTime(source.lastSuccessMs) : ""
        const info = source.errorInfo
        let problem
        switch (source.errorKind) {
        case "":
            return source.busy && !source.usage ? i18n("Loading…") : ""
        case "nologin":
            problem = i18n("No %1 subscription login found", source.cliName)
            break
        case "nocli":
            problem = i18n("%1 not found: install it, or set its program in the settings (General)", source.cliName)
            break
        case "cli":
            problem = i18n("%1 could not tell the usage: %2", source.cliName, info.message || "")
            break
        case "nostatusline":
            problem = i18n("No numbers from %1's status line yet: set it up in the settings (General), then send "
                           + "%1 a message", source.cliName)
            break
        case "unreadable":
            problem = i18n("Cannot use the login file: %1", info.message || "")
            break
        case "timeout":
            problem = i18n("No answer from the helper; will retry")
            break
        case "format":
            problem = i18n("Unexpected answer; %1 may have changed what it reports", source.cliName)
            break
        default:
            problem = i18n("Error: %1 %2", source.errorKind, info.message || "")
        }
        return lastGood ? i18n("%1 · last good %2", problem, lastGood) : problem
    }

    // The last line: when the oldest shown numbers were fetched, and that a click refreshes.
    function footerText() {
        if (sections.length === 0) {
            return anyBusy ? i18n("Loading…") : noLoginText()
        }
        const good = sections.filter(sec => sec.source.lastSuccessMs > 0).map(sec => sec.source.lastSuccessMs)
        return good.length > 0 ? i18n("Updated %1 · click to refresh", shortTime(Math.min(...good)))
            : i18n("Click to refresh")
    }

    function noLoginText() {
        const names = sources.map(s => s.cliName)
        return names.length === 0 ? i18n("Every provider is turned off in the settings")
            : i18n("No %1 login found", names.join(i18nc("between two program names", " or ")))
    }

    // A provider's own line under its rows: what went wrong, or that it is still loading; hidden when empty.
    component StatusLine: CardLabel {
        property bool error: false
        property real zoom: 1
        objectName: "status"
        Layout.fillWidth: true
        visible: text.length > 0
        font.pointSize: Kirigami.Theme.smallFont.pointSize * zoom
        wrapMode: Text.WordWrap
        color: error ? Kirigami.Theme.neutralTextColor : Kirigami.Theme.textColor
        opacity: error ? 1 : 0.6
    }

    compactRepresentation: MouseArea {
        id: compact
        // A panel sizes the applet from these; a bare MouseArea is 0 wide (stock compact items set them too).
        implicitWidth: compactRow.implicitWidth + Kirigami.Units.smallSpacing * 2
        implicitHeight: compactRow.implicitHeight
        Layout.minimumWidth: implicitWidth
        Layout.minimumHeight: implicitHeight
        onClicked: root.expanded = !root.expanded

        RowLayout {
            id: compactRow
            anchors.centerIn: parent
            spacing: Kirigami.Units.smallSpacing
            Repeater {
                // Each provider's first rows in the user's order, providers in the order of their first row.
                model: Logic.compactParts(Logic.rowsByProvider(root.layout))
                delegate: CardLabel {
                    required property var modelData
                    text: modelData.text
                    font.bold: modelData.kind === "value"
                    opacity: modelData.kind === "value" || modelData.kind === "none" ? 1 : 0.5
                    color: {
                        const level = Logic.levelOf(modelData.percent, Plasmoid.configuration.warnPercent,
                                                    Plasmoid.configuration.criticalPercent)
                        return modelData.kind !== "value" ? Kirigami.Theme.textColor
                            : Logic.levelColor(level, { normal: Kirigami.Theme.textColor, warning: root.warnColor,
                                                        critical: root.criticalColor })
                    }
                }
            }
        }
    }

    fullRepresentation: Item {
        id: full

        readonly property real baseWidth: Kirigami.Units.gridUnit * Logic.BASE_WIDTH_UNITS
        readonly property real baseHeight: Kirigami.Units.gridUnit * Logic.BASE_HEIGHT_UNITS
        readonly property string overflow: Plasmoid.configuration.overflowMode
        // "Shrink to fit" lowers this until the content fits the height; 1 in the other modes.
        property real shrink: 1
        readonly property real zoom: Logic.zoomFor(Plasmoid.configuration.sizeMode, width, baseWidth,
                                                   Plasmoid.configuration.zoomPercent) * shrink

        // What the desktop is asked for. It grows a widget's slot whenever the request rises above it after the
        // widget was placed, and never shrinks it back (D14). So on a desktop the request is the size the widget
        // has (never more than the design size), except once in its life: a widget first shown asks for the
        // design size just after it appears (`askDesign`), which grows a new widget to it, and a second later
        // `placed` is kept in its settings. In a panel the card is a popup, sized to its rows as before; "make the
        // widget taller" asks for every row.
        readonly property bool onDesktop: Plasmoid.formFactor === PlasmaCore.Types.Planar
        readonly property bool placed: Plasmoid.configuration.placedAtDesignSize
        property bool askDesign: false
        Timer {
            interval: Logic.ASK_DESIGN_AFTER_MS
            running: full.onDesktop && !full.placed && !full.askDesign && full.width > 0 && full.height > 0
            onTriggered: full.askDesign = true
        }
        Timer {
            interval: Logic.PLACED_AFTER_MS
            running: full.askDesign && !full.placed
            onTriggered: Plasmoid.configuration.placedAtDesignSize = true
        }
        readonly property bool wantDesign: askDesign && !placed
        Layout.minimumWidth: Kirigami.Units.gridUnit * Logic.MIN_WIDTH_UNITS
        Layout.preferredWidth: !onDesktop || wantDesign ? baseWidth : Logic.preferredSize(baseWidth, width)
        // "Make the widget taller" asks Plasma for room for every row; the other modes need only a little.
        Layout.minimumHeight: overflow === "grow" ? content.implicitHeight : Kirigami.Units.gridUnit * Logic.MIN_HEIGHT_UNITS
        Layout.preferredHeight: overflow === "grow" || !onDesktop ? content.implicitHeight
            : wantDesign ? baseHeight : Logic.preferredSize(baseHeight, height)

        // A layout recomputes its size only when a frame is prepared, so the fit is checked right after a
        // frame: reading the height any earlier gives the previous zoom's height, and the fit would chase it.
        property bool fitPending: false
        // The smallest scale seen overflowing at the current size; growing back stays under it. Forgotten when
        // the size, the mode or the rows change, since it then no longer describes this content.
        property real growCeiling: 1
        readonly property int rowCount: root.sections.reduce((n, sec) => n + sec.rows.length, 0)
        function refitFresh() {
            growCeiling = 1
            requestFit()
        }
        onRowCountChanged: refitFresh()
        function requestFit() {
            fitPending = true
            if (Window.window) {
                Window.window.update()
            }
        }
        function fitHeight() {
            if (overflow !== "shrink") {
                shrink = 1
                return
            }
            if (content.implicitHeight > scroll.height) {
                growCeiling = Math.min(growCeiling, shrink - Logic.CEILING_MARGIN)
            }
            const next = Logic.shrinkStep(shrink, scroll.height, content.implicitHeight, growCeiling)
            if (next !== shrink) {
                shrink = next
                requestFit()  // check the new size once it is laid out; shrinkStep's hysteresis makes this end
            }
        }
        Connections {
            target: full.Window.window
            function onFrameSwapped() {
                if (full.fitPending) {
                    full.fitPending = false
                    full.fitHeight()
                }
            }
        }
        onOverflowChanged: refitFresh()
        onHeightChanged: refitFresh()
        onWidthChanged: refitFresh()

        // A Flickable, not a ScrollView: a ScrollView is a Pane, and a Pane takes every mouse button, so a
        // right-click never reached the desktop and the widget's menu never opened. Not dragged with the mouse
        // (the wheel and the scrollbar scroll it), so it takes no button at all.
        Flickable {
            id: scroll
            objectName: "scroll"
            anchors.fill: parent
            clip: true
            interactive: false
            boundsBehavior: Flickable.StopAtBounds
            // Never sideways: the content always fills the width, and only rows that do not fit scroll. The room
            // kept for the scrollbar is updated a moment after it shows or hides, not bound to it: it shows
            // because the rows overflow, and their height depends on this width, so a binding would loop. Both
            // outcomes are stable (narrower rows still overflow, wider ones still fit), so it cannot flicker.
            property real barSpace: 0
            readonly property real availableWidth: width - barSpace
            function updateBarSpace() {
                barSpace = scrollBar.visible ? scrollBar.width : 0
            }
            contentWidth: availableWidth
            contentHeight: content.implicitHeight

            QQC2.ScrollBar.vertical: PlasmaComponents3.ScrollBar {
                id: scrollBar
                // While shrinking can still make room, a scrollbar would only flicker and change the wrapping.
                policy: full.overflow === "shrink" && full.shrink > Logic.MIN_SHRINK
                    ? QQC2.ScrollBar.AlwaysOff : QQC2.ScrollBar.AsNeeded
                onVisibleChanged: Qt.callLater(scroll.updateBarSpace)
                onWidthChanged: Qt.callLater(scroll.updateBarSpace)
            }
            // The wheel step of Plasma's own ScrollView.
            Kirigami.WheelHandler {
                target: scroll
                verticalStepSize: Application.styleHints.wheelScrollLines * 20
            }

            ColumnLayout {
                id: content
                width: scroll.availableWidth
                spacing: Kirigami.Units.largeSpacing * full.zoom
                onImplicitHeightChanged: full.requestFit()

                TapHandler {
                    onTapped: root.refreshAll(true)
                }

                RowLayout {
                    Layout.fillWidth: true
                    CardLabel {
                        Layout.fillWidth: true
                        text: root.titleText()
                        font.capitalization: Font.AllUppercase
                        font.bold: true
                        font.pointSize: Kirigami.Theme.defaultFont.pointSize * full.zoom
                        opacity: 0.7
                        elide: Text.ElideRight
                    }
                    PlasmaComponents3.BusyIndicator {
                        implicitWidth: Kirigami.Units.iconSizes.small * full.zoom
                        implicitHeight: Kirigami.Units.iconSizes.small * full.zoom
                        running: root.anyBusy
                        visible: root.anyBusy
                    }
                }

                // While each provider's rows stay together, one block per provider: its name (when there are
                // several), its rows in the user's order, and its own line when something went wrong. Once the
                // user's order mixes providers, one block of every row, each named with its provider, and the
                // providers' own lines after it (Logic.arrangeRows).
                Repeater {
                    model: root.layout.blocks
                    delegate: ColumnLayout {
                        id: block
                        required property var modelData
                        // The provider of a per-provider block; null for the mixed one.
                        readonly property var section: modelData.section >= 0 ? root.sections[modelData.section] : null
                        Layout.fillWidth: true
                        spacing: Kirigami.Units.largeSpacing * full.zoom

                        CardLabel {
                            objectName: "header"
                            Layout.fillWidth: true
                            visible: block.section !== null && root.sections.length > 1
                            text: block.section ? block.section.source.providerName : ""
                            font.capitalization: Font.AllUppercase
                            font.pointSize: Kirigami.Theme.smallFont.pointSize * full.zoom
                            opacity: 0.6
                        }
                        Repeater {
                            model: block.modelData.rows
                            delegate: UsageRow {
                                required property var modelData
                                readonly property var source: root.sections[modelData.section].source
                                Layout.fillWidth: true
                                rowId: modelData.row.id || ""
                                title: root.layout.mixed && root.sections.length > 1
                                    ? i18nc("a service's name, then one of its usage rows", "%1 · %2",
                                            source.providerName, modelData.row.label)
                                    : modelData.row.label
                                percent: modelData.row.percent
                                resetText: root.resetText(modelData.row.resets_at, modelData.row.group !== "session")
                                stale: source.errorKind !== "" && source.usage !== null
                                outdated: root.isOutdated(source)
                                outdatedColor: root.staleColor
                                level: Logic.levelOf(modelData.row.percent, Plasmoid.configuration.warnPercent,
                                                     Plasmoid.configuration.criticalPercent)
                                warnColor: root.warnColor
                                criticalColor: root.criticalColor
                                zoom: full.zoom
                            }
                        }
                        StatusLine {
                            text: block.section ? root.sectionStatus(block.section.source) : ""
                            error: block.section !== null && block.section.source.errorKind !== ""
                            zoom: full.zoom
                        }
                    }
                }
                Repeater {
                    model: root.layout.mixed ? root.sections : []
                    delegate: StatusLine {
                        required property var modelData
                        readonly property string problem: root.sectionStatus(modelData.source)
                        text: problem ? i18nc("a service's name, then what went wrong with it", "%1: %2",
                                              modelData.source.providerName, problem) : ""
                        error: modelData.source.errorKind !== ""
                        zoom: full.zoom
                    }
                }

                CardLabel {
                    Layout.fillWidth: true
                    text: root.footerText()
                    font.pointSize: Kirigami.Theme.smallFont.pointSize * full.zoom
                    wrapMode: Text.WordWrap
                    opacity: 0.6
                }
            }
        }
    }
}
