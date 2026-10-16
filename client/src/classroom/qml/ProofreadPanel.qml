import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "theme"

// 教材校对面板（REV1B 画布 · Agent B）
// 校对清单来自**真实的** needs_review 记录（由离线流水线在生成课程时写入 manifest），
// 不是演示动画。每项必须由使用者显式确认；未确认项会**阻塞**发布门禁（见「发布」页）。
Rectangle {
    id: root
    color: ClassroomTheme.bg

    function reasonText(r) {
        if (r === "phonetic_unknown") return "音标未知 —— 未编造音标，已省略该字段（诚实降级）"
        if (r === "answer_needs_human") return "答案缺失/非法 —— 未默认判分，标记为「答案待人工确认」"
        return r || "需人工确认"
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: ClassroomTheme.spacingLg
        spacing: ClassroomTheme.spacingMd

        RowLayout {
            Layout.fillWidth: true
            spacing: ClassroomTheme.spacingMd
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2
                Text {
                    text: "教材校对"
                    font.family: ClassroomTheme.fontFamily
                    font.pixelSize: ClassroomTheme.fontXl
                    font.bold: true
                    color: ClassroomTheme.text
                }
                Text {
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                    text: classroom.draftTitle.length > 0
                          ? ("课程：" + classroom.draftTitle + "（" + classroom.draftCourseId + "）")
                          : "尚未打开课程"
                    font.family: ClassroomTheme.fontFamily
                    font.pixelSize: ClassroomTheme.fontSm
                    color: ClassroomTheme.textSecondary
                }
            }
            Button {
                text: "去书库选课"
                onClicked: classroom.setPage("library")
            }
        }

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: st.implicitHeight + 20
            radius: ClassroomTheme.radiusMd
            color: classroom.reviewUnresolved > 0
                   ? Qt.rgba(217 / 255, 131 / 255, 23 / 255, 0.12) : ClassroomTheme.primarySoft
            border.width: 1
            border.color: classroom.reviewUnresolved > 0 ? ClassroomTheme.warn : ClassroomTheme.primary
            Text {
                id: st
                anchors.fill: parent
                anchors.margins: 10
                text: classroom.proofreadState
                wrapMode: Text.WordWrap
                font.family: ClassroomTheme.fontFamily
                font.pixelSize: ClassroomTheme.fontMd
                color: ClassroomTheme.text
            }
        }

        // 指令⑧（契约强制，UI_DESIGN §4.5）：版面风险提醒=一般性固定文案；
        // 不得作针对性声明（仅当后端返回真实检测信号时才允许显示针对性提示）。
        Text {
            Layout.fillWidth: true
            text: "当教材为多栏排版时，抽取顺序可能与阅读顺序不一致，请重点核对"
            wrapMode: Text.WordWrap
            font.family: ClassroomTheme.fontFamily
            font.pixelSize: ClassroomTheme.fontXs
            color: ClassroomTheme.textSecondary
        }

        ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: classroom.reviewTotal > 0
            clip: true
            contentWidth: availableWidth

            ColumnLayout {
                width: parent.width
                spacing: ClassroomTheme.spacingSm

                Repeater {
                    model: classroom.proofreadEntries
                    delegate: Rectangle {
                        id: entryCard
                        required property var modelData
                        required property int index
                        Layout.fillWidth: true
                        implicitHeight: itemCol.implicitHeight + 20
                        radius: ClassroomTheme.radiusMd
                        color: ClassroomTheme.surface
                        border.width: 1
                        border.color: modelData.resolved ? ClassroomTheme.success
                                       : (modelData.critical ? ClassroomTheme.danger
                                                             : ClassroomTheme.border)
                        property string noteDraft: ""

                        ColumnLayout {
                            id: itemCol
                            anchors.fill: parent
                            anchors.margins: 10
                            spacing: ClassroomTheme.spacingXs

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: ClassroomTheme.spacingSm
                                Text {
                                    text: (index + 1) + "."
                                    font.family: ClassroomTheme.fontFamily
                                    font.pixelSize: ClassroomTheme.fontMd
                                    color: ClassroomTheme.textPlaceholder
                                }
                                Text {
                                    Layout.fillWidth: true
                                    wrapMode: Text.WordWrap
                                    text: modelData.label
                                    font.family: ClassroomTheme.fontFamily
                                    font.pixelSize: ClassroomTheme.fontMd
                                    font.bold: true
                                    color: ClassroomTheme.text
                                }
                                Rectangle {
                                    radius: 999
                                    implicitWidth: critT.implicitWidth + 14
                                    implicitHeight: critT.implicitHeight + 6
                                    color: modelData.critical
                                           ? Qt.rgba(217 / 255, 70 / 255, 63 / 255, 0.12)
                                           : ClassroomTheme.surfaceAlt
                                    Text {
                                        id: critT
                                        anchors.centerIn: parent
                                        text: modelData.critical ? "关键" : "非关键"
                                        font.family: ClassroomTheme.fontFamily
                                        font.pixelSize: ClassroomTheme.fontXs
                                        color: modelData.critical ? ClassroomTheme.danger
                                                                  : ClassroomTheme.textSecondary
                                    }
                                }
                                Button {
                                    visible: modelData.resolved
                                    text: "重新打开"
                                    onClicked: classroom.reopenEntry(index)
                                }
                            }

                            // 原文对照（来自知识库快照 readback 的原教材文本）
                            Text {
                                Layout.fillWidth: true
                                visible: (modelData.original || "").length > 0
                                wrapMode: Text.WordWrap
                                text: "原文：" + modelData.original
                                font.family: ClassroomTheme.fontFamily
                                font.pixelSize: ClassroomTheme.fontXs
                                color: ClassroomTheme.textSecondary
                            }
                            Text {
                                Layout.fillWidth: true
                                wrapMode: Text.WordWrap
                                text: "位置 " + modelData.where + " · " + root.reasonText(modelData.reason)
                                font.family: ClassroomTheme.fontFamily
                                font.pixelSize: ClassroomTheme.fontXs
                                color: ClassroomTheme.textSecondary
                            }

                            // 修正：补音标
                            RowLayout {
                                Layout.fillWidth: true
                                visible: modelData.kind === "phonetic" && !modelData.resolved
                                spacing: ClassroomTheme.spacingSm
                                Text {
                                    text: "音标"
                                    font.family: ClassroomTheme.fontFamily
                                    font.pixelSize: ClassroomTheme.fontSm
                                    color: ClassroomTheme.textSecondary
                                }
                                TextField {
                                    id: ipaInput
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    placeholderText: "输入音标，如 /həˈləʊ/（可留空）"
                                    text: modelData.value || ""
                                    onTextEdited: entryCard.noteDraft = text
                                }
                                Button {
                                    text: "应用音标"
                                    enabled: ipaInput.text.trim().length > 0
                                    onClicked: classroom.applyPhoneticFix(index, ipaInput.text)
                                }
                            }

                            // 修正：补练习答案（关键项必须修正）
                            RowLayout {
                                Layout.fillWidth: true
                                visible: modelData.kind === "answer" && !modelData.resolved
                                spacing: ClassroomTheme.spacingSm
                                Text {
                                    text: "正确答案"
                                    font.family: ClassroomTheme.fontFamily
                                    font.pixelSize: ClassroomTheme.fontSm
                                    color: ClassroomTheme.textSecondary
                                }
                                Repeater {
                                    model: modelData.options || []
                                    delegate: Button {
                                        required property var modelData
                                        required property int index
                                        text: String.fromCharCode(65 + index) + ". " + modelData
                                        onClicked: classroom.applyAnswerFix(entryCard.index, index)
                                    }
                                }
                            }

                            // 非关键缺失：记录原因后接受（关键项不提供该入口）
                            RowLayout {
                                Layout.fillWidth: true
                                visible: !modelData.critical && !modelData.resolved
                                spacing: ClassroomTheme.spacingSm
                                TextField {
                                    id: acceptNote
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    placeholderText: "接受缺失的原因（必填），如：低龄教材无需音标"
                                }
                                Button {
                                    text: "接受缺失"
                                    enabled: acceptNote.text.trim().length > 0
                                    onClicked: {
                                        classroom.acceptEntryAsNonCritical(index, acceptNote.text)
                                        acceptNote.text = ""
                                    }
                                }
                            }

                            Text {
                                Layout.fillWidth: true
                                visible: modelData.resolved
                                wrapMode: Text.WordWrap
                                text: "✓ 已处理" + ((modelData.note || "").length > 0
                                                   ? "（" + modelData.note + "）" : "")
                                font.family: ClassroomTheme.fontFamily
                                font.pixelSize: ClassroomTheme.fontXs
                                color: ClassroomTheme.success
                            }
                        }
                    }
                }
                Item { Layout.preferredHeight: ClassroomTheme.spacingSm }
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 140
            visible: classroom.reviewTotal === 0
            spacing: ClassroomTheme.spacingSm
            Item { Layout.fillHeight: true }
            Text {
                Layout.alignment: Qt.AlignHCenter
                text: classroom.draftTitle.length === 0
                      ? "请先在「书库」打开一门课程"
                      : "本课程没有需要人工确认的条目"
                font.family: ClassroomTheme.fontFamily
                font.pixelSize: ClassroomTheme.fontLg
                color: ClassroomTheme.textSecondary
            }
            Text {
                Layout.alignment: Qt.AlignHCenter
                Layout.maximumWidth: 560
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                text: "校对完成后，「发布」页会重新计算真实业务门禁（来源绑定 / 待确认项 / 未解决项）。"
                font.family: ClassroomTheme.fontFamily
                font.pixelSize: ClassroomTheme.fontSm
                color: ClassroomTheme.textPlaceholder
            }
            Item { Layout.fillHeight: true }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: ClassroomTheme.spacingSm
            Text {
                Layout.fillWidth: true
                elide: Text.ElideRight
                visible: classroom.proofreadSaveState.length > 0
                text: classroom.proofreadSaveState
                font.family: ClassroomTheme.fontFamily
                font.pixelSize: ClassroomTheme.fontXs
                color: ClassroomTheme.textSecondary
            }
            Button {
                text: "保存校对结果"
                enabled: classroom.draftCourseId.length > 0
                onClicked: classroom.saveProofread()
            }
            Button {
                text: "下一步：发布（Mock）"
                highlighted: true
                onClicked: classroom.setPage("publish")
            }
        }
    }
}
