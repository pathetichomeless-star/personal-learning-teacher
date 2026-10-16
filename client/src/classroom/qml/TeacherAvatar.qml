import QtQuick
import "theme"

// 老师形象容器（V1）：数字人未就绪时显示清晰的静态占位形象。
// 就绪时可在 place 处放入真实数字人组件（本轮不依赖、不阻塞课堂）。
Item {
    id: root
    property string teacherName: ""
    property bool showHint: true
    implicitWidth: 180
    implicitHeight: 180

    readonly property int d: Math.min(width, height)

    Rectangle {
        id: circle
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.top
        width: root.d
        height: root.d
        radius: width / 2
        color: ClassroomTheme.avatarBg
        border.width: 2
        border.color: ClassroomTheme.border

        Text {
            anchors.centerIn: parent
            text: root.teacherName ? root.teacherName.substring(0, 1) : "AI"
            font.family: ClassroomTheme.fontFamily
            font.pixelSize: Math.max(20, circle.width * 0.38)
            font.bold: true
            color: ClassroomTheme.primary
        }
    }

    Text {
        anchors.top: circle.bottom
        anchors.topMargin: ClassroomTheme.spacingSm
        anchors.horizontalCenter: parent.horizontalCenter
        visible: root.showHint
        text: "数字人未启用 · 静态占位形象"
        font.family: ClassroomTheme.fontFamily
        font.pixelSize: ClassroomTheme.fontXs
        color: ClassroomTheme.textPlaceholder
    }
}
