import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "theme"

// 左侧 AI 老师区
Rectangle {
    id: root
    signal changeTeacherRequested()
    color: ClassroomTheme.surface
    radius: ClassroomTheme.radiusLg
    border.width: 1
    border.color: ClassroomTheme.border

    readonly property string tName: classroom.selectedTeacherName
    readonly property var tObj: classroom.selectedTeacher

    function statusColor(s) {
        if (s === "练习") return ClassroomTheme.warn
        if (s === "讲解") return ClassroomTheme.primary
        if (s === "已结束" || s === "断开") return ClassroomTheme.danger
        return ClassroomTheme.textSecondary
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: ClassroomTheme.spacingLg
        spacing: ClassroomTheme.spacingMd

        Text {
            text: "AI 老师"
            font.family: ClassroomTheme.fontFamily
            font.pixelSize: ClassroomTheme.fontXs
            color: ClassroomTheme.textSecondary
        }

        TeacherAvatar {
            Layout.alignment: Qt.AlignHCenter
            Layout.preferredWidth: Math.min(root.width - 40, 190)
            Layout.preferredHeight: Layout.preferredWidth + 24
            teacherName: root.tName
        }

        Text {
            Layout.fillWidth: true
            text: root.tName
            horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideRight
            font.family: ClassroomTheme.fontFamily
            font.pixelSize: ClassroomTheme.fontLg
            font.bold: true
            color: ClassroomTheme.text
        }

        Text {
            Layout.fillWidth: true
            horizontalAlignment: Text.AlignHCenter
            text: {
                var lang = root.tObj && root.tObj.language ? root.tObj.language : "未提供"
                var v = root.tObj && root.tObj.voice_id ? root.tObj.voice_id : "默认"
                return "教学语言 " + lang + " · 音色 " + v
            }
            font.family: ClassroomTheme.fontFamily
            font.pixelSize: ClassroomTheme.fontSm
            color: ClassroomTheme.textSecondary
            wrapMode: Text.WordWrap
        }

        Rectangle {
            Layout.alignment: Qt.AlignHCenter
            radius: 999
            implicitWidth: st.implicitWidth + 20
            implicitHeight: st.implicitHeight + 8
            color: Qt.rgba(0, 0, 0, 0)
            border.width: 1
            border.color: root.statusColor(classroom.status)
            Text {
                id: st
                anchors.centerIn: parent
                text: "状态：" + classroom.status
                font.family: ClassroomTheme.fontFamily
                font.pixelSize: ClassroomTheme.fontSm
                color: root.statusColor(classroom.status)
            }
        }

        Item { Layout.fillHeight: true }

        Button {
            Layout.fillWidth: true
            text: "更换老师"
            onClicked: root.changeTeacherRequested()
        }
    }
}
