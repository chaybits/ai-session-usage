import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.kcmutils as KCM
import "UsageLogic.js" as Logic

KCM.SimpleKCM {
    id: page

    property alias cfg_refreshMinutes: refreshSpin.value
    property string cfg_claudeSource
    property string cfg_claudeSourceDefault
    property alias cfg_claudeCommand: claudeCommandField.text
    property string cfg_claudeCommandDefault
    property alias cfg_showClaude: showClaude.checked
    property alias cfg_credentialsPath: credentialsField.text
    property alias cfg_showCodex: showCodex.checked
    property alias cfg_codexCommand: codexCommandField.text
    property string cfg_codexCommandDefault
    property alias cfg_codexAuthPath: codexField.text
    property int cfg_refreshMinutesDefault
    property bool cfg_showClaudeDefault
    property string cfg_credentialsPathDefault
    property bool cfg_showCodexDefault
    property string cfg_codexAuthPathDefault

    Kirigami.FormLayout {
        QQC2.SpinBox {
            id: refreshSpin
            Kirigami.FormData.label: i18n("Refresh every (minutes):")
            from: 1
            to: 120
        }

        Kirigami.Separator {
            Kirigami.FormData.isSection: true
            Kirigami.FormData.label: i18n("Claude Code")
        }
        QQC2.CheckBox {
            id: showClaude
            text: i18n("Show the Claude Code limits")
        }
        QQC2.RadioButton {
            id: fromClaudeCode
            Kirigami.FormData.label: i18n("From:")
            enabled: showClaude.checked
            text: i18n("Claude Code itself (asked for its usage; no login is read here)")
            checked: page.cfg_claudeSource !== "statusline"
            onToggled: if (checked) page.cfg_claudeSource = "claudecode"
        }
        QQC2.TextField {
            id: claudeCommandField
            Kirigami.FormData.label: i18n("Claude Code program:")
            visible: fromClaudeCode.checked
            enabled: showClaude.checked
            placeholderText: i18n("claude, found on the PATH")
        }
        QQC2.RadioButton {
            id: fromStatusLine
            enabled: showClaude.checked
            text: i18n("Claude Code's status line (no login is read; 5-hour and weekly only)")
            checked: page.cfg_claudeSource === "statusline"
            onToggled: if (checked) page.cfg_claudeSource = "statusline"
        }
        QQC2.Label {
            Layout.maximumWidth: Kirigami.Units.gridUnit * 24
            visible: fromStatusLine.checked
            wrapMode: Text.WordWrap
            font: Kirigami.Theme.smallFont
            text: i18n("Claude Code passes the 5-hour and weekly limits to its status line. Add this to "
                       + "~/.claude/settings.json; the numbers then arrive with each of Claude Code's answers, "
                       + "and show the time they were seen:")
        }
        QQC2.TextArea {
            objectName: "statusLineSnippet"
            Layout.maximumWidth: Kirigami.Units.gridUnit * 24
            visible: fromStatusLine.checked
            readOnly: true
            selectByMouse: true
            wrapMode: TextEdit.WrapAnywhere
            font.family: "monospace"
            font.pointSize: Kirigami.Theme.smallFont.pointSize
            // quoted for the shell, as the card's own command is: a home folder with a space must not split it
            text: JSON.stringify({ statusLine: { type: "command", command: "python3 -B "
                + Logic.shellQuote(Logic.scriptPath(Qt.resolvedUrl("../code/statusline_tap.py"))) } })
        }
        QQC2.TextField {
            id: credentialsField
            Kirigami.FormData.label: i18n("Login file:")
            enabled: showClaude.checked
            placeholderText: "~/.claude/.credentials.json"
        }

        Kirigami.Separator {
            Kirigami.FormData.isSection: true
            Kirigami.FormData.label: i18n("ChatGPT (Codex)")
        }
        QQC2.CheckBox {
            id: showCodex
            text: i18n("Show the ChatGPT (Codex) limits (Codex itself is asked; no login is read here)")
        }
        QQC2.TextField {
            id: codexCommandField
            Kirigami.FormData.label: i18n("Codex program:")
            enabled: showCodex.checked
            placeholderText: i18n("codex, found on the PATH")
        }
        QQC2.TextField {
            id: codexField
            Kirigami.FormData.label: i18n("Login file:")
            enabled: showCodex.checked
            placeholderText: "~/.codex/auth.json"
        }

        QQC2.Label {
            Layout.maximumWidth: Kirigami.Units.gridUnit * 20
            wrapMode: Text.WordWrap
            font: Kirigami.Theme.smallFont
            text: i18n("Neither login file is read: each is only checked to exist, so that someone without that program "
                       + "sees no section for it. Claude Code and Codex are asked for their own usage and use their own "
                       + "logins. A provider with no login file is left out of the widget.")
        }
    }
}
