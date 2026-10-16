import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "theme"

// 右侧学习互动区：字幕 / 词汇 / 课堂笔记
Rectangle {
    id: root
    color: ClassroomTheme.surface
    radius: ClassroomTheme.radiusLg
    border.width: 1
    border.color: ClassroomTheme.border

    readonly property string tab: classroom.activeTab

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: ClassroomTheme.spacingMd
        spacing: ClassroomTheme.spacingSm

        RowLayout {
            Layout.fillWidth: true
            spacing: ClassroomTheme.spacingXs
            Repeater {
                model: [["transcript", "字幕"], ["vocab", "词汇"], ["notes", "课堂笔记"]]
                Rectangle {
                    required property var modelData
                    Layout.fillWidth: true
                    implicitHeight: 30
                    radius: ClassroomTheme.radiusSm
                    color: root.tab === modelData[0] ? ClassroomTheme.primarySoft
                                                     : ClassroomTheme.surfaceAlt
                    border.width: 1
                    border.color: root.tab === modelData[0] ? ClassroomTheme.primary
                                                           : ClassroomTheme.border
                    Text {
                        anchors.centerIn: parent
                        text: modelData[1]
                        font.family: ClassroomTheme.fontFamily
                        font.pixelSize: ClassroomTheme.fontSm
                        color: root.tab === modelData[0] ? ClassroomTheme.primary
                                                         : ClassroomTheme.textSecondary
                    }
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: classroom.setActiveTab(modelData[0])
                    }
                }
            }
        }

        Rectangle { Layout.fillWidth: true; height: 1; color: ClassroomTheme.border }

        // 字幕
        ListView {
            id: tList
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: root.tab === "transcript"
            clip: true
            spacing: ClassroomTheme.spacingSm
            model: classroom.transcript
            onCountChanged: positionViewAtEnd()
            delegate: Rectangle {
                required property var modelData
                width: tList.width
                implicitHeight: bub.implicitHeight + 16
                radius: ClassroomTheme.radiusMd
                color: modelData.role === "student" ? ClassroomTheme.primarySoft
                                                    : ClassroomTheme.surfaceAlt
                Text {
                    id: bub
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.margins: ClassroomTheme.spacingSm
                    text: (modelData.role === "student" ? "我：" : "老师：") + modelData.text
                    wrapMode: Text.WordWrap
                    font.family: ClassroomTheme.fontFamily
                    font.pixelSize: ClassroomTheme.fontSm
                    color: ClassroomTheme.text
                }
            }
        }

        // 词汇（P2-5：单词与音标分行；音标缺失诚实提示；口音统一标注「未标注」）
        ListView {
            id: vList
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: root.tab === "vocab"
            clip: true
            spacing: ClassroomTheme.spacingSm
            model: classroom.slideVocab
            delegate: Column {
                required property var modelData
                width: vList.width
                spacing: 2
                Text {
                    text: modelData.word
                    font.family: ClassroomTheme.fontFamily
                    font.pixelSize: ClassroomTheme.fontMd
                    font.bold: true
                    color: ClassroomTheme.primary
                }
                Text {
                    text: (modelData.phonetic || "").length > 0
                          ? modelData.phonetic + "（口音：未标注）"
                          : "暂无音标（课件未提供，不编造）"
                    font.family: ClassroomTheme.fontFamily
                    font.pixelSize: ClassroomTheme.fontSm
                    color: (modelData.phonetic || "").length > 0
                           ? ClassroomTheme.textSecondary : ClassroomTheme.textPlaceholder
                }
                Text {
                    text: modelData.meaning || ""
                    font.family: ClassroomTheme.fontFamily
                    font.pixelSize: ClassroomTheme.fontSm
                    color: ClassroomTheme.textSecondary
                }
            }
        }

        // 课堂笔记（P1-1/P2-10：真实持久化记录——含错题；可查看、可删除，跨重启保留）
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: root.tab === "notes"
            spacing: ClassroomTheme.spacingXs

            RowLayout {
                Layout.fillWidth: true
                Text {
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                    text: "学习记录（本课程，共 %1 条）".arg(classroom.noteRecordCount)
                    font.family: ClassroomTheme.fontFamily
                    font.pixelSize: ClassroomTheme.fontXs
                    color: ClassroomTheme.textSecondary
                }
                Button {
                    text: "清空本课"
                    enabled: classroom.noteRecordCount > 0
                    onClicked: classroom.clearCourseRecords()
                }
            }
            Text {
                Layout.fillWidth: true
                visible: classroom.recordsNotice.length > 0
                wrapMode: Text.WordWrap
                text: classroom.recordsNotice
                font.family: ClassroomTheme.fontFamily
                font.pixelSize: ClassroomTheme.fontXs
                color: ClassroomTheme.warn
            }
            ListView {
                id: nList
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                spacing: ClassroomTheme.spacingXs
                model: classroom.noteRecords
                delegate: Rectangle {
                    required property var modelData
                    width: nList.width
                    implicitHeight: noteCol.implicitHeight + 12
                    radius: ClassroomTheme.radiusSm
                    color: modelData.result === "wrong"
                           ? Qt.rgba(217 / 255, 70 / 255, 63 / 255, 0.08)
                           : ClassroomTheme.surfaceAlt
                    ColumnLayout {
                        id: noteCol
                        anchors.fill: parent
                        anchors.margins: 6
                        spacing: 1
                        RowLayout {
                            Layout.fillWidth: true
                            Text {
                                Layout.fillWidth: true
                                elide: Text.ElideRight
                                text: (modelData.result === "wrong" ? "✗ 需复习"
                                      : modelData.result === "ungraded" ? "待确认"
                                      : modelData.kind === "note" ? "• 笔记" : "记录")
                                      + " · " + modelData.time
                                font.family: ClassroomTheme.fontFamily
                                font.pixelSize: ClassroomTheme.fontXs
                                color: modelData.result === "wrong"
                                       ? ClassroomTheme.danger : ClassroomTheme.textPlaceholder
                            }
                            Button {
                                text: "删除"
                                onClicked: classroom.deleteNoteRecord(modelData.index)
                            }
                        }
                        Text {
                            Layout.fillWidth: true
                            wrapMode: Text.WordWrap
                            visible: (modelData.prompt || "").length > 0
                            text: modelData.prompt
                            font.family: ClassroomTheme.fontFamily
                            font.pixelSize: ClassroomTheme.fontSm
                            color: ClassroomTheme.text
                        }
                        Text {
                            Layout.fillWidth: true
                            wrapMode: Text.WordWrap
                            visible: (modelData.answer || "").length > 0
                            text: "作答：" + modelData.answer
                            font.family: ClassroomTheme.fontFamily
                            font.pixelSize: ClassroomTheme.fontXs
                            color: ClassroomTheme.textSecondary
                        }
                    }
                }
            }
        }

        Text {
            Layout.fillWidth: true
            visible: (root.tab === "transcript" && classroom.transcript.length === 0)
                     || (root.tab === "vocab" && classroom.slideVocab.length === 0)
                     || (root.tab === "notes" && classroom.noteRecordCount === 0)
            text: root.tab === "notes"
                  ? "暂无学习记录——作答练习或写笔记后会自动保存，重启后仍保留。"
                  : "暂无内容——开始学习后这里会显示本地演示的教学文字。"
            wrapMode: Text.WordWrap
            font.family: ClassroomTheme.fontFamily
            font.pixelSize: ClassroomTheme.fontXs
            color: ClassroomTheme.textPlaceholder
        }
    }
}
