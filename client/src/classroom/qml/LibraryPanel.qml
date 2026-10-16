import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "theme"

// 书库面板（REV1B 画布 · Agent B）
// 真实数据：扫描「课堂隔离目录 /library」+「随包离线演示」+「随包本地演示课程」，
// 每条都经过冻结契约 v1 校验；无效条目照实显示原因，不静默隐藏。
Rectangle {
    id: root
    color: ClassroomTheme.bg

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: ClassroomTheme.spacingLg
        spacing: ClassroomTheme.spacingMd

        // 头部
        RowLayout {
            Layout.fillWidth: true
            spacing: ClassroomTheme.spacingMd
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2
                Text {
                    text: "书库"
                    font.family: ClassroomTheme.fontFamily
                    font.pixelSize: ClassroomTheme.fontXl
                    font.bold: true
                    color: ClassroomTheme.text
                }
                Text {
                    Layout.fillWidth: true
                    text: "共 %1 门课程（来源已标注；全部按冻结契约 v1 校验，未通过的照实显示原因）".arg(classroom.libraryCount)
                    font.family: ClassroomTheme.fontFamily
                    font.pixelSize: ClassroomTheme.fontSm
                    color: ClassroomTheme.textSecondary
                }
            }
            Button {
                text: "重新扫描"
                onClicked: classroom.refreshLibrary()
            }
        }

        // 继续上次学习（P1-1/P2-2：来自真实学习位置文件）
        Rectangle {
            Layout.fillWidth: true
            visible: Object.keys(classroom.resumeInfo).length > 0
                     && (classroom.resumeInfo.course_id || "").length > 0
            implicitHeight: resumeRow.implicitHeight + 20
            radius: ClassroomTheme.radiusMd
            color: ClassroomTheme.primarySoft
            border.width: 1
            border.color: ClassroomTheme.primary
            RowLayout {
                id: resumeRow
                anchors.fill: parent
                anchors.margins: 10
                spacing: ClassroomTheme.spacingSm
                Text {
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    text: "继续上次学习：" + (classroom.resumeInfo.title || classroom.resumeInfo.course_id)
                          + " · 第 " + ((classroom.resumeInfo.slide_index || 0) + 1)
                          + " 页（保存于隔离目录，跨重启有效）"
                    font.family: ClassroomTheme.fontFamily
                    font.pixelSize: ClassroomTheme.fontSm
                    color: ClassroomTheme.text
                }
                Button {
                    text: "继续上次学习"
                    highlighted: true
                    onClicked: classroom.resumeLastLearning()
                }
            }
        }

        // 错误条（如实显示，不隐藏）
        Rectangle {
            Layout.fillWidth: true
            visible: classroom.libraryError.length > 0
            implicitHeight: errText.implicitHeight + 20
            radius: ClassroomTheme.radiusMd
            color: Qt.rgba(217 / 255, 70 / 255, 63 / 255, 0.10)
            border.width: 1
            border.color: ClassroomTheme.danger
            Text {
                id: errText
                anchors.fill: parent
                anchors.margins: 10
                text: "书库读取问题：" + classroom.libraryError
                wrapMode: Text.WordWrap
                font.family: ClassroomTheme.fontFamily
                font.pixelSize: ClassroomTheme.fontSm
                color: ClassroomTheme.danger
            }
        }

        // 空状态（先于列表，避免被填充高度的列表挤到屏幕外）
        ColumnLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 160
            visible: classroom.libraryCount === 0
            spacing: ClassroomTheme.spacingSm
            Item { Layout.fillHeight: true }
            Text {
                Layout.alignment: Qt.AlignHCenter
                text: "书库为空"
                font.family: ClassroomTheme.fontFamily
                font.pixelSize: ClassroomTheme.fontLg
                color: ClassroomTheme.textSecondary
            }
            Text {
                Layout.alignment: Qt.AlignHCenter
                Layout.maximumWidth: 520
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                text: "可在「导入」页查看教材导入现状。若需生成离线演示课程，请运行 tools/classroom_offline_pipeline.py。"
                font.family: ClassroomTheme.fontFamily
                font.pixelSize: ClassroomTheme.fontSm
                color: ClassroomTheme.textPlaceholder
            }
            Item { Layout.fillHeight: true }
        }

        ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: classroom.libraryCount > 0
            clip: true
            contentWidth: availableWidth

            Flow {
                width: parent.width
                spacing: ClassroomTheme.spacingMd

                Repeater {
                    model: classroom.libraryItems
                    delegate: Rectangle {
                        required property var modelData
                        width: Math.min(340, Math.max(240, root.width - 2 * ClassroomTheme.spacingLg))
                        height: 176
                        radius: ClassroomTheme.radiusLg
                        color: ClassroomTheme.surface
                        border.width: 1
                        border.color: modelData.valid ? ClassroomTheme.border : ClassroomTheme.danger

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: ClassroomTheme.spacingMd
                            spacing: ClassroomTheme.spacingSm

                            RowLayout {
                                Layout.fillWidth: true
                                Text {
                                    Layout.fillWidth: true
                                    text: modelData.title || "（未命名课程）"
                                    elide: Text.ElideRight
                                    font.family: ClassroomTheme.fontFamily
                                    font.pixelSize: ClassroomTheme.fontLg
                                    font.bold: true
                                    color: ClassroomTheme.text
                                }
                                Rectangle {
                                    radius: 999
                                    implicitWidth: srcBadge.implicitWidth + 16
                                    implicitHeight: srcBadge.implicitHeight + 6
                                    // P2-3：随包演示课程明确标记「演示教材」，避免误认为本人导入
                                    color: modelData.origin === "bundled-demo"
                                           || modelData.origin === "bundled-local"
                                           ? Qt.rgba(217 / 255, 131 / 255, 23 / 255, 0.14)
                                           : (modelData.source === "user-textbook"
                                              ? ClassroomTheme.primarySoft
                                              : (modelData.source === "admin-knowledge"
                                                 ? Qt.rgba(31 / 255, 157 / 255, 99 / 255, 0.14)
                                                 : ClassroomTheme.surfaceAlt))
                                    Text {
                                        id: srcBadge
                                        anchors.centerIn: parent
                                        text: (modelData.origin === "bundled-demo"
                                               || modelData.origin === "bundled-local")
                                              ? "演示教材"
                                              : (modelData.source === "user-textbook" ? "用户教材"
                                                 : (modelData.source === "admin-knowledge" ? "知识库"
                                                    : "本地演示"))
                                        font.family: ClassroomTheme.fontFamily
                                        font.pixelSize: ClassroomTheme.fontXs
                                        color: ClassroomTheme.textSecondary
                                    }
                                }
                            }

                            Text {
                                Layout.fillWidth: true
                                elide: Text.ElideRight
                                text: "%1 · rev %2 · %3 课次 / %4 页"
                                    .arg(modelData.course_id || "")
                                    .arg(modelData.revision)
                                    .arg(modelData.lessons)
                                    .arg(modelData.slides)
                                font.family: ClassroomTheme.fontFamily
                                font.pixelSize: ClassroomTheme.fontSm
                                color: ClassroomTheme.textSecondary
                            }

                            Text {
                                Layout.fillWidth: true
                                // R2-7：学生界面不显示内部技术标识 doc_id；
                                // 来源诊断信息仅保留在「导入」页「诊断信息」折叠区内。
                                wrapMode: Text.WordWrap
                                visible: modelData.source === "user-textbook"
                                         && classroom.gatewayOpen
                                text: "来源 doc_id：" + modelData.doc_id
                                font.family: ClassroomTheme.fontFamily
                                font.pixelSize: ClassroomTheme.fontXs
                                color: ClassroomTheme.textPlaceholder
                            }

                            Text {
                                Layout.fillWidth: true
                                wrapMode: Text.WordWrap
                                visible: modelData.needs_review > 0
                                text: "⚠ 待人工确认 " + modelData.needs_review + " 项"
                                font.family: ClassroomTheme.fontFamily
                                font.pixelSize: ClassroomTheme.fontXs
                                color: ClassroomTheme.warn
                            }

                            Text {
                                Layout.fillWidth: true
                                wrapMode: Text.WordWrap
                                visible: !modelData.valid
                                text: "不可用：" + (modelData.error || "")
                                font.family: ClassroomTheme.fontFamily
                                font.pixelSize: ClassroomTheme.fontXs
                                color: ClassroomTheme.danger
                            }

                            Item { Layout.fillHeight: true }

                            RowLayout {
                                Layout.fillWidth: true
                                Button {
                                    text: "打开并进入课堂"
                                    highlighted: true
                                    enabled: modelData.valid
                                    onClicked: classroom.openLibraryItem(modelData.course_id)
                                }
                                Button {
                                    text: "去校对"
                                    enabled: modelData.valid
                                    onClicked: {
                                        classroom.openLibraryItem(modelData.course_id)
                                        classroom.setPage("proofread")
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
