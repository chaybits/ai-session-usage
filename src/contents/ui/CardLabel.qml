import QtQuick
import org.kde.plasma.components as PlasmaComponents3

// Every label of the widget. Native rendering draws the font at each size it is given, fitted to the pixel
// grid; Qt's default draws every size from one prepared outline, so text that grows with the widget's width
// (fit to width) looked like a stretched picture, with softer edges the larger it got (ARCHITECTURE D10).
PlasmaComponents3.Label {
    renderType: Text.NativeRendering
}
