import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import "theme"

// 导入面板（REV1B 画布 · Agent B）
// 三条硬规则：
//   ① 本机解析服务**未开放**（独立安全复核通过前）→ 必须显示真实原因，绝不假装成功；
//   ② 能力表来自**本地事实**（哪些格式真的有解析器），不可硬编码"支持"；
//   ③ 「解析进度」显示的是离线流水线**真实记录**的阶段，不是动画。
Rectangle {
    id: root
    color: ClassroomTheme.bg

    property string preflightText: ""
    property bool preflightOk: false
    property bool preflightDone: false

    FileDialog {
        id: picker
        title: "选择本地教材文件（仅用于本地预检）"
        fileMode: FileDialog.OpenFile
        nameFilters: ["教材文件 (*.txt *.md *.pdf *.docx *.pptx *.epub)", "全部文件 (*)"]
        onAccepted: {
            var p = String(selectedFile)
            // QML 侧只做**本地事实**预检（路径/扩展名），不读取文件内容、不发网络
            var name = p.split("/").pop()
            var lower = name.toLowerCase()
            var ext = lower.indexOf(".") >= 0 ? lower.substring(lower.lastIndexOf(".")) : ""
            var known = [".txt", ".md", ".pdf", ".docx", ".pptx", ".epub"]
            root.preflightOk = known.indexOf(ext) >= 0
            root.preflightDone = true
            root.preflightText = known.indexOf(ext) >= 0
                ? ("本地预检：文件「%1」扩展名 %2 属于受支持格式。\n接下来需要「本机解析服务」完成解析与提交知识库——该服务当前未开放（原因见上方横幅）。"
                    .arg(name).arg(ext))
                : ("本地预检：文件「%1」的扩展名 %2 暂不支持，无法解析。"
                    .arg(name).arg(ext || "（无）"))
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: ClassroomTheme.spacingLg
        spacing: ClassroomTheme.spacingMd

        Text {
            text: "导入教材"
            font.family: ClassroomTheme.fontFamily
            font.pixelSize: ClassroomTheme.fontXl
            font.bold: true
            color: ClassroomTheme.text
        }

        // ① 硬门禁横幅
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: bannerCol.implicitHeight + 24
            radius: ClassroomTheme.radiusLg
            color: Qt.rgba(217 / 255, 131 / 255, 23 / 255, 0.12)
            border.width: 1
            border.color: ClassroomTheme.warn
            ColumnLayout {
                id: bannerCol
                anchors.fill: parent
                anchors.margins: ClassroomTheme.spacingMd
                spacing: ClassroomTheme.spacingXs
                Text {
                    text: "本机解析服务：未开放"
                    font.family: ClassroomTheme.fontFamily
                    font.pixelSize: ClassroomTheme.fontLg
                    font.bold: true
                    color: ClassroomTheme.warn
                }
                Text {
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    text: classroom.gatewayBlockedReason
                    font.family: ClassroomTheme.fontFamily
                    font.pixelSize: ClassroomTheme.fontSm
                    color: ClassroomTheme.text
                }
                Text {
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    text: "契约：学生客户端将来只经 /cls/knowledge/*（白名单路由）访问；" +
                          "/admin/knowledge/* 是既有内部接口，「不向学生开放」。详见 api/STUDENT_CLS_KNOWLEDGE_CONTRACT.md。"
                    font.family: ClassroomTheme.fontFamily
                    font.pixelSize: ClassroomTheme.fontXs
                    color: ClassroomTheme.textSecondary
                }
            }
        }

        ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            contentWidth: availableWidth

            ColumnLayout {
                width: parent.width
                spacing: ClassroomTheme.spacingMd

                // ② 能力表
                Text {
                    text: "支持的格式（本地事实）"
                    font.family: ClassroomTheme.fontFamily
                    font.pixelSize: ClassroomTheme.fontMd
                    font.bold: true
                    color: ClassroomTheme.text
                }
                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: fmtCol.implicitHeight + 20
                    radius: ClassroomTheme.radiusMd
                    color: ClassroomTheme.surface
                    border.width: 1
                    border.color: ClassroomTheme.border
                    ColumnLayout {
                        id: fmtCol
                        anchors.fill: parent
                        anchors.margins: 10
                        spacing: 6
                        Repeater {
                            model: classroom.importFormats
                            delegate: RowLayout {
                                required property var modelData
                                Layout.fillWidth: true
                                spacing: ClassroomTheme.spacingSm
                                Rectangle {
                                    implicitWidth: 10; implicitHeight: 10; radius: 5
                                    // R2-7：解析服务未开放时一律不用绿色「可用」圆点，
                                    // 避免把尚未开放的格式显示为可直接使用。
                                    color: (modelData.available && classroom.gatewayOpen)
                                           ? ClassroomTheme.success
                                           : ClassroomTheme.border
                                }
                                Text {
                                    Layout.preferredWidth: 76
                                    text: modelData.ext
                                    font.family: ClassroomTheme.fontFamily
                                    font.pixelSize: ClassroomTheme.fontSm
                                    color: ClassroomTheme.text
                                }
                                Text {
                                    Layout.preferredWidth: 110
                                    text: modelData.label
                                    elide: Text.ElideRight
                                    font.family: ClassroomTheme.fontFamily
                                    font.pixelSize: ClassroomTheme.fontSm
                                    color: ClassroomTheme.textSecondary
                                }
                                Text {
                                    Layout.fillWidth: true
                                    wrapMode: Text.WordWrap
                                    // R2-7：解析服务未开放时统一注明「暂不可用」，
                                    // 不向学生显示「本地解析器可用」字样。
                                    text: modelData.available
                                          ? (classroom.gatewayOpen
                                             ? (modelData.reason.length > 0 ? "⚠ " + modelData.reason
                                                                            : "本地解析器可用")
                                             : "格式受支持，但解析服务未开放，暂不可用")
                                          : "✕ " + modelData.reason
                                    font.family: ClassroomTheme.fontFamily
                                    font.pixelSize: ClassroomTheme.fontXs
                                    color: modelData.available
                                           ? (classroom.gatewayOpen
                                              ? (modelData.reason.length > 0 ? ClassroomTheme.warn
                                                                             : ClassroomTheme.textSecondary)
                                              : ClassroomTheme.textSecondary)
                                           : ClassroomTheme.danger
                                }
                            }
                        }
                    }
                }

                // ③ 本地预检
                Text {
                    text: "本地预检（不读取内容、不发网络）"
                    font.family: ClassroomTheme.fontFamily
                    font.pixelSize: ClassroomTheme.fontMd
                    font.bold: true
                    color: ClassroomTheme.text
                }
                RowLayout {
                    Layout.fillWidth: true
                    Button { text: "选择本地教材文件…"; onClicked: picker.open() }
                    Button {
                        text: "查看离线流水线记录（解析进度）"
                        enabled: classroom.offlineDemoAvailable
                        onClicked: classroom.loadOfflinePipelineRecord()
                    }
                    Item { Layout.fillWidth: true }
                }
                Text {
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    visible: classroom.offlineDemoAvailable
                    text: "离线演示教材：" + classroom.offlineDemoName
                    font.family: ClassroomTheme.fontFamily
                    font.pixelSize: ClassroomTheme.fontXs
                    color: ClassroomTheme.textPlaceholder
                }
                Text {
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    visible: !classroom.offlineDemoAvailable
                    text: "未找到离线演示记录。可运行：python tools/classroom_offline_pipeline.py --out <课堂数据目录>"
                    font.family: ClassroomTheme.fontFamily
                    font.pixelSize: ClassroomTheme.fontXs
                    color: ClassroomTheme.textPlaceholder
                }
                Rectangle {
                    Layout.fillWidth: true
                    visible: root.preflightDone
                    implicitHeight: preCol.implicitHeight + 20
                    radius: ClassroomTheme.radiusMd
                    color: ClassroomTheme.surfaceAlt
                    border.width: 1
                    border.color: root.preflightOk ? ClassroomTheme.border : ClassroomTheme.danger
                    Text {
                        id: preCol
                        anchors.fill: parent
                        anchors.margins: 10
                        text: root.preflightText
                        wrapMode: Text.WordWrap
                        font.family: ClassroomTheme.fontFamily
                        font.pixelSize: ClassroomTheme.fontSm
                        color: ClassroomTheme.text
                    }
                }

                // 解析进度（真实阶段记录）
                Text {
                    Layout.topMargin: ClassroomTheme.spacingSm
                    text: "解析进度"
                    font.family: ClassroomTheme.fontFamily
                    font.pixelSize: ClassroomTheme.fontMd
                    font.bold: true
                    color: ClassroomTheme.text
                }
                Text {
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    text: classroom.importMessage
                    font.family: ClassroomTheme.fontFamily
                    font.pixelSize: ClassroomTheme.fontSm
                    color: classroom.importState === "done" ? ClassroomTheme.text
                         : (classroom.importState === "error" ? ClassroomTheme.danger
                                                             : ClassroomTheme.textSecondary)
                }
                // P2-11：技术标识（doc_id / content_hash 等）收进「诊断信息」，默认折叠
                TextArea {
                    Layout.fillWidth: true
                    visible: classroom.importDiagnostics.length > 0 && diagChecked.checked
                    readOnly: true
                    wrapMode: TextArea.Wrap
                    text: classroom.importDiagnostics
                    font.family: ClassroomTheme.fontFamily
                    font.pixelSize: ClassroomTheme.fontXs
                    color: ClassroomTheme.textPlaceholder
                }
                CheckBox {
                    id: diagChecked
                    visible: classroom.importDiagnostics.length > 0
                    text: "显示诊断信息（技术标识）"
                    font.family: ClassroomTheme.fontFamily
                    font.pixelSize: ClassroomTheme.fontXs
                }
                Rectangle {
                    Layout.fillWidth: true
                    visible: classroom.importStages.length > 0
                    implicitHeight: stageCol.implicitHeight + 20
                    radius: ClassroomTheme.radiusMd
                    color: ClassroomTheme.surface
                    border.width: 1
                    border.color: ClassroomTheme.border
                    ColumnLayout {
                        id: stageCol
                        anchors.fill: parent
                        anchors.margins: 10
                        spacing: 6
                        Repeater {
                            model: classroom.importStages
                            delegate: RowLayout {
                                required property var modelData
                                required property int index
                                Layout.fillWidth: true
                                spacing: ClassroomTheme.spacingSm
                                Text {
                                    Layout.preferredWidth: 26
                                    text: (index + 1) + "."
                                    font.family: ClassroomTheme.fontFamily
                                    font.pixelSize: ClassroomTheme.fontSm
                                    color: ClassroomTheme.textPlaceholder
                                }
                                Text {
                                    Layout.preferredWidth: 96
                                    text: modelData.stage
                                    font.family: ClassroomTheme.fontFamily
                                    font.pixelSize: ClassroomTheme.fontSm
                                    font.bold: true
                                    color: modelData.ok ? ClassroomTheme.text : ClassroomTheme.danger
                                }
                                Text {
                                    Layout.fillWidth: true
                                    wrapMode: Text.WordWrap
                                    text: modelData.detail
                                    font.family: ClassroomTheme.fontFamily
                                    font.pixelSize: ClassroomTheme.fontXs
                                    color: ClassroomTheme.textSecondary
                                }
                                Text {
                                    Layout.preferredWidth: 74
                                    horizontalAlignment: Text.AlignRight
                                    text: modelData.elapsed_ms + " ms"
                                    font.family: ClassroomTheme.fontFamily
                                    font.pixelSize: ClassroomTheme.fontXs
                                    color: ClassroomTheme.textPlaceholder
                                }
                            }
                        }
                    }
                }
                Item { Layout.preferredHeight: ClassroomTheme.spacingMd }
            }
        }
    }
}
