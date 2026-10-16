import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "theme"

// 课程发布（Mock 演练）面板（REV1B 画布 · Agent B）
// 硬边界：
//   * 本页**不发任何网络请求**、不写入任何发布存储；
//   * 真实发布服务端路由本轮**未实现**，独立安全复核通过前不开放；
//   * 门禁是**真实计算**的（基于已打开课程 + 校对结果 + 知识库快照复核），不是勾选动画。
Rectangle {
    id: root
    color: ClassroomTheme.bg

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: ClassroomTheme.spacingLg
        spacing: ClassroomTheme.spacingMd

        Text {
            text: "课程发布"
            font.family: ClassroomTheme.fontFamily
            font.pixelSize: ClassroomTheme.fontXl
            font.bold: true
            color: ClassroomTheme.text
        }

        // Mock 横幅（始终可见，杜绝误解为真实发布）
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: mockT.implicitHeight + 20
            radius: ClassroomTheme.radiusLg
            color: Qt.rgba(47 / 255, 107 / 255, 255 / 255, 0.10)
            border.width: 1
            border.color: ClassroomTheme.primary
            Text {
                id: mockT
                anchors.fill: parent
                anchors.margins: 10
                text: classroom.publishMockBanner
                wrapMode: Text.WordWrap
                font.family: ClassroomTheme.fontFamily
                font.pixelSize: ClassroomTheme.fontSm
                color: ClassroomTheme.text
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: ClassroomTheme.spacingSm
            Button {
                text: "运行发布门禁演练"
                highlighted: true
                enabled: classroom.draftCourseId.length > 0
                onClicked: classroom.runPublishMock()
            }
            Text {
                Layout.fillWidth: true
                elide: Text.ElideRight
                text: classroom.draftCourseId.length > 0
                      ? ("课程：" + classroom.draftTitle + " · 来源 " + classroom.draftSource
                         + " · 待确认 " + classroom.reviewUnresolved + " 项")
                      : "尚未打开课程（请先到「书库」打开一门课程）"
                font.family: ClassroomTheme.fontFamily
                font.pixelSize: ClassroomTheme.fontSm
                color: ClassroomTheme.textSecondary
            }
        }

        Text {
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            visible: classroom.publishState.length > 0
            text: classroom.publishState
            font.family: ClassroomTheme.fontFamily
            font.pixelSize: ClassroomTheme.fontMd
            font.bold: true
            color: ClassroomTheme.text
        }

        ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            contentWidth: availableWidth

            ColumnLayout {
                width: parent.width
                spacing: ClassroomTheme.spacingSm

                // 门禁清单
                Repeater {
                    model: classroom.publishGates
                    delegate: Rectangle {
                        required property var modelData
                        Layout.fillWidth: true
                        implicitHeight: gateRow.implicitHeight + 20
                        radius: ClassroomTheme.radiusMd
                        color: ClassroomTheme.surface
                        border.width: 1
                        border.color: modelData.ok ? ClassroomTheme.success : ClassroomTheme.danger
                        RowLayout {
                            id: gateRow
                            anchors.fill: parent
                            anchors.margins: 10
                            spacing: ClassroomTheme.spacingSm
                            Rectangle {
                                implicitWidth: 22; implicitHeight: 22; radius: 11
                                color: modelData.ok ? ClassroomTheme.success : ClassroomTheme.danger
                                Text {
                                    anchors.centerIn: parent
                                    text: modelData.ok ? "✓" : "✕"
                                    color: "white"
                                    font.pixelSize: 13
                                    font.bold: true
                                }
                            }
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 2
                                Text {
                                    Layout.fillWidth: true
                                    wrapMode: Text.WordWrap
                                    text: modelData.name
                                    font.family: ClassroomTheme.fontFamily
                                    font.pixelSize: ClassroomTheme.fontMd
                                    font.bold: true
                                    color: ClassroomTheme.text
                                }
                                Text {
                                    Layout.fillWidth: true
                                    wrapMode: Text.WordWrap
                                    text: modelData.detail
                                    font.family: ClassroomTheme.fontFamily
                                    font.pixelSize: ClassroomTheme.fontXs
                                    color: ClassroomTheme.textSecondary
                                }
                            }
                        }
                    }
                }

                // 空态（P2-12：精简留白，直接给出行动指引）
                Text {
                    Layout.fillWidth: true
                    visible: classroom.publishGates.length === 0
                    wrapMode: Text.WordWrap
                    text: "尚未运行门禁演练——点击上方按钮即可查看当前课程的真实业务门禁结果。"
                    font.family: ClassroomTheme.fontFamily
                    font.pixelSize: ClassroomTheme.fontSm
                    color: ClassroomTheme.textPlaceholder
                }
                // P2-11：演练日志（开发向信息）收进诊断折叠区，默认不显示
                CheckBox {
                    id: pubDiag
                    visible: classroom.publishLog.length > 0
                    text: "显示诊断信息（演练日志）"
                    font.family: ClassroomTheme.fontFamily
                    font.pixelSize: ClassroomTheme.fontXs
                }
                Repeater {
                    model: pubDiag.checked ? classroom.publishLog : []
                    delegate: Text {
                        required property var modelData
                        required property int index
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                        text: "#" + (index + 1) + " @ " + modelData.at + " → "
                              + modelData.ok + "/" + modelData.total + " 门禁通过"
                        font.family: ClassroomTheme.fontFamily
                        font.pixelSize: ClassroomTheme.fontXs
                        color: ClassroomTheme.textSecondary
                    }
                }
                Item { Layout.preferredHeight: ClassroomTheme.spacingMd }
            }
        }

        Text {
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            text: "本页为门禁演练：即使全部通过也不会产生可被他人访问的课程；真实发布待独立安全复核通过后开放。"
            font.family: ClassroomTheme.fontFamily
            font.pixelSize: ClassroomTheme.fontXs
            color: ClassroomTheme.textPlaceholder
        }
    }
}
