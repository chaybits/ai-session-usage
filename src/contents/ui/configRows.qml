import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.kcmutils as KCM
import "UsageLogic.js" as Logic

// Which rows the widget shows, and in what order. The list is every row the widget has shown so far (it records
// them as they arrive), so a new cap appears here after its first appearance on the widget. Moving a row stores
// the whole list's order; rows of different services may be mixed, and the widget then names the service in
// each row.
KCM.SimpleKCM {
    id: page

    property var cfg_hiddenRows: []
    property var cfg_hiddenRowsDefault: []
    property var cfg_rowOrder: []
    property var cfg_rowOrderDefault: []
    property string cfg_knownRows
    property string cfg_knownRowsDefault

    // The rows as the widget orders them: the user's order first, the rest by service and first sight.
    readonly property var rows: Logic.applyOrder(Logic.defaultKnownOrder(Logic.parseKnownRows(cfg_knownRows)),
                                                 cfg_rowOrder, k => k.id)

    function providerName(id) {
        return id === "codex" ? i18n("ChatGPT") : id === "claude" ? i18n("Claude") : id
    }

    function setShown(id, shown) {
        const hidden = (cfg_hiddenRows || []).filter(h => h !== id)
        if (!shown) {
            hidden.push(id)
        }
        cfg_hiddenRows = hidden
    }

    function move(index, delta) {
        const moved = Logic.moveId(rows.map(k => k.id), index, delta)
        if (moved !== null) {
            cfg_rowOrder = moved
        }
    }

    ColumnLayout {
        QQC2.Label {
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            text: page.rows.length > 0
                ? i18n("Untick a row to hide it from the widget; use the arrows to change the order. Rows of "
                       + "different services may be mixed: the widget then names the service in each row.")
                : i18n("No rows yet: they are listed here once the widget has shown them.")
        }
        Repeater {
            model: page.rows
            delegate: RowLayout {
                id: entry
                required property var modelData
                required property int index
                Layout.fillWidth: true

                QQC2.CheckBox {
                    Layout.fillWidth: true
                    text: page.providerName(entry.modelData.provider) + " · " + entry.modelData.label
                    checked: (page.cfg_hiddenRows || []).indexOf(entry.modelData.id) < 0
                    onToggled: page.setShown(entry.modelData.id, checked)
                }
                QQC2.ToolButton {
                    objectName: "up:" + entry.modelData.id
                    icon.name: "go-up"
                    enabled: entry.index > 0
                    onClicked: page.move(entry.index, -1)
                    QQC2.ToolTip.text: i18n("Move up")
                    QQC2.ToolTip.visible: hovered
                    QQC2.ToolTip.delay: Kirigami.Units.toolTipDelay
                    Accessible.name: i18n("Move %1 up", entry.modelData.label)
                }
                QQC2.ToolButton {
                    objectName: "down:" + entry.modelData.id
                    icon.name: "go-down"
                    enabled: entry.index < page.rows.length - 1
                    onClicked: page.move(entry.index, 1)
                    QQC2.ToolTip.text: i18n("Move down")
                    QQC2.ToolTip.visible: hovered
                    QQC2.ToolTip.delay: Kirigami.Units.toolTipDelay
                    Accessible.name: i18n("Move %1 down", entry.modelData.label)
                }
            }
        }
        QQC2.Button {
            text: i18n("Default order")
            icon.name: "edit-undo"
            visible: (page.cfg_rowOrder || []).length > 0
            onClicked: page.cfg_rowOrder = []
        }
    }
}
