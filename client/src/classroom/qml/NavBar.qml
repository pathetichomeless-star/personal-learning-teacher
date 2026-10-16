import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "theme"

// 主导航条（REV1B 画布落地 · Agent B）
// 设计要点：横向 Flickable 承载 5 个栏目，任意窗口宽度下都不越界——
// 宽窗全部可见，窄窗可横向滚动（不使用会被裁剪的固定行）。
Rectangle {
    id: nav
    color: ClassroomTheme.surface
    implicitHeight: 48
    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: ClassroomTheme.border }

    Flickable {
        id: flick
        anchors.fill: parent
        anchors.leftMargin: ClassroomTheme.spacingLg
        anchors.rightMargin: ClassroomTheme.spacingLg
        contentWidth: chips.width
        contentHeight: height
        flickableDirection: Flickable.HorizontalFlick
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.horizontal: ScrollBar { policy: flick.contentWidth > flick.width
                                                  ? ScrollBar.AlwaysOn : ScrollBar.AlwaysOff
                                          height: 4 }

        Row {
            id: chips
            height: parent.height
            spacing: ClassroomTheme.spacingXs

            Repeater {
                model: classroom.pages
                delegate: Rectangle {
                    required property var modelData
                    height: chips.height
                    width: Math.max(72, label.implicitWidth + 28)
                    color: classroom.page === modelData.key ? ClassroomTheme.primarySoft
                                                            : "transparent"
                    radius: ClassroomTheme.radiusMd

                    Rectangle {
                        visible: classroom.page === modelData.key
                        anchors.bottom: parent.bottom
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: parent.width - 20
                        height: 2
                        radius: 2
                        color: ClassroomTheme.primary
                    }
                    Text {
                        id: label
                        anchors.centerIn: parent
                        text: modelData.label
                        font.family: ClassroomTheme.fontFamily
                        font.pixelSize: ClassroomTheme.fontMd
                        font.bold: classroom.page === modelData.key
                        color: classroom.page === modelData.key ? ClassroomTheme.primary
                                                                : ClassroomTheme.textSecondary
                    }
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: classroom.setPage(modelData.key)
                    }
                }
            }
        }
    }
}
