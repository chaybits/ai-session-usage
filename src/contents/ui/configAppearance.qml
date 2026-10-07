import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.kcmutils as KCM
import org.kde.kquickcontrols as KQC2

KCM.SimpleKCM {
    id: page

    property string cfg_sizeMode
    property string cfg_sizeModeDefault
    property alias cfg_zoomPercent: zoomSpin.value
    property int cfg_zoomPercentDefault
    property string cfg_overflowMode
    property string cfg_overflowModeDefault
    property alias cfg_staleMinutes: staleSpin.value
    property int cfg_staleMinutesDefault
    property alias cfg_staleColor: staleColor.color
    property color cfg_staleColorDefault
    property alias cfg_warnPercent: warnSpin.value
    property int cfg_warnPercentDefault
    property alias cfg_criticalPercent: criticalSpin.value
    property int cfg_criticalPercentDefault
    property alias cfg_warnColor: warnColor.color
    property color cfg_warnColorDefault
    property alias cfg_criticalColor: criticalColor.color
    property color cfg_criticalColorDefault

    Kirigami.FormLayout {
        QQC2.RadioButton {
            Kirigami.FormData.label: i18n("Size:")
            text: i18n("Fit to the widget's width (resize it to zoom)")
            checked: page.cfg_sizeMode !== "fixed"
            onToggled: if (checked) page.cfg_sizeMode = "fit"
        }
        RowLayout {
            QQC2.RadioButton {
                id: fixedRadio
                text: i18n("Fixed zoom:")
                checked: page.cfg_sizeMode === "fixed"
                onToggled: if (checked) page.cfg_sizeMode = "fixed"
            }
            QQC2.SpinBox {
                id: zoomSpin
                enabled: fixedRadio.checked
                from: 50
                to: 300
                stepSize: 10
                textFromValue: (value, locale) => i18n("%1 %", value)
                valueFromText: (text, locale) => parseInt(text, 10)
            }
        }

        QQC2.RadioButton {
            Kirigami.FormData.label: i18n("When the rows do not fit:")
            text: i18n("Scroll")
            checked: page.cfg_overflowMode !== "grow" && page.cfg_overflowMode !== "shrink"
            onToggled: if (checked) page.cfg_overflowMode = "scroll"
        }
        QQC2.RadioButton {
            text: i18n("Make the widget taller")
            checked: page.cfg_overflowMode === "grow"
            onToggled: if (checked) page.cfg_overflowMode = "grow"
        }
        QQC2.RadioButton {
            text: i18n("Shrink the text to fit")
            checked: page.cfg_overflowMode === "shrink"
            onToggled: if (checked) page.cfg_overflowMode = "shrink"
        }

        Kirigami.Separator {
            Kirigami.FormData.isSection: true
        }
        QQC2.SpinBox {
            id: staleSpin
            Kirigami.FormData.label: i18n("Mark numbers as outdated after:")
            from: 0
            to: 1440
            textFromValue: (value, locale) => value === 0 ? i18n("Never") : i18np("%1 minute", "%1 minutes", value)
            valueFromText: (text, locale) => parseInt(text, 10) || 0
        }
        KQC2.ColorButton {
            id: staleColor
            Kirigami.FormData.label: i18n("Outdated colour:")
            enabled: staleSpin.value > 0
            dialogTitle: i18n("Colour of outdated numbers")
        }
        QQC2.Label {
            Layout.maximumWidth: Kirigami.Units.gridUnit * 20
            wrapMode: Text.WordWrap
            font: Kirigami.Theme.smallFont
            text: i18n("Set this above the refresh interval: at an equal value the numbers would turn this colour "
                       + "for a moment before every refresh.")
        }

        Kirigami.Separator {
            Kirigami.FormData.isSection: true
        }
        QQC2.SpinBox {
            id: warnSpin
            Kirigami.FormData.label: i18n("Warning colour from:")
            from: 0
            to: 100
            textFromValue: (value, locale) => value === 0 ? i18n("Never") : i18n("%1 %", value)
            valueFromText: (text, locale) => parseInt(text, 10) || 0
        }
        KQC2.ColorButton {
            id: warnColor
            Kirigami.FormData.label: i18n("Warning colour:")
            enabled: warnSpin.value > 0
            showAlphaChannel: false
            dialogTitle: i18n("Colour from the warning level up")
        }
        QQC2.SpinBox {
            id: criticalSpin
            Kirigami.FormData.label: i18n("Critical colour from:")
            from: 0
            to: 100
            textFromValue: (value, locale) => value === 0 ? i18n("Never") : i18n("%1 %", value)
            valueFromText: (text, locale) => parseInt(text, 10) || 0
        }
        KQC2.ColorButton {
            id: criticalColor
            Kirigami.FormData.label: i18n("Critical colour:")
            enabled: criticalSpin.value > 0
            showAlphaChannel: false
            dialogTitle: i18n("Colour from the critical level up")
        }
    }
}
