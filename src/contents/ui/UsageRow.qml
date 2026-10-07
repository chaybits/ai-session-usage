import QtQuick
import QtQuick.Layouts
import org.kde.plasma.components as PlasmaComponents3
import org.kde.kirigami as Kirigami
import "UsageLogic.js" as Logic

// One usage window: name and percentage, a bar, and the reset countdown.
ColumnLayout {
    id: row

    property string rowId
    property string title
    property real percent: 0
    property string resetText
    // The provider's last fetch failed: the numbers are kept but dimmed.
    property bool stale: false
    // The numbers are older than the user's "outdated after" setting: drawn in the outdated colour.
    property bool outdated: false
    property color outdatedColor: Kirigami.Theme.neutralTextColor
    // "normal", "warning" or "critical", from the user's thresholds, and the user's colours for the two.
    property string level: "normal"
    property color warnColor: Kirigami.Theme.neutralTextColor
    property color criticalColor: Kirigami.Theme.negativeTextColor
    property real zoom: 1

    readonly property color textColor: outdated ? outdatedColor : Kirigami.Theme.textColor
    readonly property color percentColor: outdated ? outdatedColor
        : Logic.levelColor(level, { normal: Kirigami.Theme.textColor, warning: warnColor, critical: criticalColor })

    spacing: Kirigami.Units.smallSpacing * zoom
    opacity: stale ? 0.55 : 1

    RowLayout {
        Layout.fillWidth: true
        CardLabel {
            objectName: "title:" + row.rowId
            Layout.fillWidth: true
            text: row.title
            elide: Text.ElideRight
            color: row.textColor
            font.pointSize: Kirigami.Theme.defaultFont.pointSize * row.zoom
        }
        CardLabel {
            objectName: "percent:" + row.rowId
            text: Math.round(row.percent) + "%"
            font.bold: true
            font.pointSize: Kirigami.Theme.defaultFont.pointSize * row.zoom
            color: row.percentColor
        }
    }
    PlasmaComponents3.ProgressBar {
        id: bar
        objectName: "bar:" + row.rowId
        Layout.fillWidth: true
        Layout.preferredHeight: implicitHeight * row.zoom
        from: 0
        to: 100
        value: Math.min(100, Math.max(0, row.percent))
        // The bar follows the percentage's colour once a threshold is passed or the data is outdated.
        Kirigami.Theme.inherit: row.level === "normal" && !row.outdated
        Kirigami.Theme.highlightColor: row.percentColor
    }
    CardLabel {
        Layout.fillWidth: true
        visible: text.length > 0
        text: row.resetText
        font.pointSize: Kirigami.Theme.smallFont.pointSize * row.zoom
        color: row.textColor
        opacity: 0.7
        elide: Text.ElideRight
    }
}
