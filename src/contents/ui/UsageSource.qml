import QtQuick
import org.kde.plasma.plasma5support as P5Support
import "UsageLogic.js" as Logic

// One provider's data: runs contents/code/fetch_usage.py for it, keeps its last good answer, and polls
// and retries on its own schedule, so a rate limit on one provider never delays the other. Not drawn.
Item {
    id: source
    visible: false

    required property string providerId     // "claude" or "codex", the helper's --provider
    required property string providerName   // shown in the widget
    required property string cliName        // the program whose session refreshes the login
    required property string scriptPath
    property string credentialsPath: ""
    // Claude only: "claudecode" (ask Claude Code itself, headless; the default) or "statusline" (read what Claude
    // Code passed its status line); empty for a provider with one way (Codex). `program` names this provider's
    // CLI when it is not on the PATH, passed with `programOption` ("--claude" or "--codex")
    property string dataSource: ""
    property string program: ""
    property string programOption: ""
    property int pollMs: 300000

    // Last successful result; kept and shown dimmed while later fetches fail.
    property var usage: null
    property string errorKind: ""
    property var errorInfo: ({})
    property bool busy: false
    property double lastSuccessMs: 0
    property double lastAttemptMs: 0
    // Current fast-retry step in ms after a network or server failure (0 = none), see Logic.nextPoll.
    property int retryStepMs: 0
    // The poll interval actually scheduled (the rate-limit text reads it, so it never promises another time).
    readonly property int scheduledMs: pollTimer.interval

    signal answered(var result)

    P5Support.DataSource {
        id: runner
        engine: "executable"
        connectedSources: []
        onNewData: function (sourceName, data) {
            disconnectSource(sourceName)
            watchdog.stop()
            source.busy = false
            source.handleOutput(data["stdout"] || "", data["stderr"] || "")
        }
    }

    Timer {
        id: pollTimer
        interval: source.pollMs
        repeat: true
        running: true
        onTriggered: source.refresh(false)
    }

    // The helper's 15 s timeout bounds each network step, not the run (the DNS lookup is not covered,
    // and a server sending a byte every few seconds never trips it); this bounds the run.
    Timer {
        id: watchdog
        interval: Logic.WATCHDOG_MS
        onTriggered: {
            // Drop the orphaned source so it cannot linger (that also ends the helper), and say what happened.
            for (const name of runner.connectedSources.slice()) {
                runner.disconnectSource(name)
            }
            source.busy = false
            source.errorKind = "timeout"
            source.errorInfo = ({})
        }
    }

    onPollMsChanged: {
        pollTimer.interval = pollMs
        pollTimer.restart()
    }

    // A corrected login file, or another source, should be tried at once, not at the next poll. Only once the
    // source is complete: a value set while it is being created arrives here too, and a run started then is
    // lost (the runner is not ready), leaving the source busy until the watchdog.
    property bool completed: false
    onCredentialsPathChanged: if (completed) refresh(false)
    onDataSourceChanged: if (completed) refresh(false)
    onProgramChanged: if (completed) refresh(false)

    Component.onCompleted: {
        completed = true
        refresh(false)
    }

    function shellQuote(s) {
        return "'" + String(s).replace(/'/g, "'\\''") + "'"
    }

    function refresh(manual) {
        if (busy) {
            return
        }
        if (manual && Date.now() - lastAttemptMs < Logic.TAP_THROTTLE_MS) {
            return
        }
        busy = true
        lastAttemptMs = Date.now()
        // -B: no __pycache__ beside the helper (it would hold this machine's paths, and src/** ships whole)
        let cmd = "python3 -B " + shellQuote(scriptPath) + " --provider " + shellQuote(providerId)
        if (dataSource) {
            cmd += " --source " + dataSource
        }
        if (program && programOption) {
            cmd += " " + programOption + " " + shellQuote(program)
        }
        if (credentialsPath) {
            cmd += " " + shellQuote(credentialsPath)
        }
        watchdog.restart()
        // The trailing comment keeps every source name unique, so each run really executes.
        runner.connectSource(cmd + " #" + lastAttemptMs)
    }

    function handleOutput(stdout, stderr) {
        const result = Logic.parseOutput(stdout, stderr)
        if (result.ok) {
            usage = result
            errorKind = ""
            errorInfo = ({})
            // numbers from Claude Code's status line are as old as Claude Code's last answer, not this read
            lastSuccessMs = typeof result.captured_at === "number" ? result.captured_at * 1000 : Date.now()
        } else {
            errorKind = result.error || "unknown"
            errorInfo = result
        }
        const next = Logic.nextPoll(result, retryStepMs, pollMs)
        retryStepMs = next.step
        pollTimer.interval = next.intervalMs
        pollTimer.restart()
        answered(result)
    }
}
