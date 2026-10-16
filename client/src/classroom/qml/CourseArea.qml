import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "theme"

// 中央主教学区（屏幕占比最大）：课件展示 + 翻页 + 练习
Rectangle {
    id: root
    signal requestCoursePicker()
    color: ClassroomTheme.surface
    radius: ClassroomTheme.radiusLg
    border.width: 1
    border.color: ClassroomTheme.border

    readonly property var s: classroom.currentSlide
    readonly property bool hasSlide: classroom.slideCount > 0 && classroom.slideIndex >= 0
    function isT(t) { return root.s && root.s.type === t }
    // 已知 slide.type 闭枚举（与 course_schema.v1.json 一致）。
    // 未知类型的**权威**处理是整包 fail-closed 拒绝（见契约 §3.6.1）；此处仅为渲染层
    // 的**防御性兜底**——即便被绕过校验，也绝不静默渲染空白页。
    readonly property var knownSlideTypes: ["cover", "vocab", "sentence", "practice", "summary"]
    readonly property bool slideTypeUnknown: root.hasSlide && root.s
        && root.knownSlideTypes.indexOf(String(root.s.type)) < 0

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: ClassroomTheme.spacingLg
        spacing: ClassroomTheme.spacingMd

        // 标题行：课程 / 课时 / 页码
        RowLayout {
            Layout.fillWidth: true
            spacing: ClassroomTheme.spacingSm
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2
                Text {
                    Layout.fillWidth: true
                    text: classroom.currentCourseTitle || "未选择课程"
                    font.family: ClassroomTheme.fontFamily
                    font.pixelSize: ClassroomTheme.fontLg
                    font.bold: true
                    color: ClassroomTheme.text
                    elide: Text.ElideRight
                }
                Text {
                    Layout.fillWidth: true
                    text: classroom.currentLessonTitle || "请先选择课时"
                    font.family: ClassroomTheme.fontFamily
                    font.pixelSize: ClassroomTheme.fontSm
                    color: ClassroomTheme.textSecondary
                    elide: Text.ElideRight
                }
            }
            Rectangle {
                visible: root.hasSlide
                radius: 999
                implicitWidth: pg.implicitWidth + 20
                implicitHeight: pg.implicitHeight + 8
                color: ClassroomTheme.primarySoft
                Text {
                    id: pg
                    anchors.centerIn: parent
                    text: "第 %1 / %2 页".arg(classroom.slideIndex + 1).arg(classroom.slideCount)
                    font.family: ClassroomTheme.fontFamily
                    font.pixelSize: ClassroomTheme.fontSm
                    color: ClassroomTheme.primary
                }
            }
        }

        Rectangle { Layout.fillWidth: true; height: 1; color: ClassroomTheme.border }

        // 讲解身份诚实标注（P2-4）+ 恢复位置提示（P1-1）
        Text {
            Layout.fillWidth: true
            visible: root.hasSlide
            text: classroom.narratorLabel
            font.family: ClassroomTheme.fontFamily
            font.pixelSize: ClassroomTheme.fontXs
            color: ClassroomTheme.textPlaceholder
            elide: Text.ElideRight
        }
        Rectangle {
            Layout.fillWidth: true
            visible: classroom.restoreBanner.length > 0
            implicitHeight: restoreT.implicitHeight + 16
            radius: ClassroomTheme.radiusMd
            color: ClassroomTheme.primarySoft
            Text {
                id: restoreT
                anchors.fill: parent
                anchors.margins: 8
                text: classroom.restoreBanner
                wrapMode: Text.WordWrap
                font.family: ClassroomTheme.fontFamily
                font.pixelSize: ClassroomTheme.fontSm
                color: ClassroomTheme.primary
            }
        }

        // 空状态
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: !root.hasSlide
            spacing: ClassroomTheme.spacingMd
            Item { Layout.fillHeight: true }
            Text {
                Layout.alignment: Qt.AlignHCenter
                text: classroom.courseCount > 0 ? "请选择一门课程开始学习" : "课程数据不可用"
                font.family: ClassroomTheme.fontFamily
                font.pixelSize: ClassroomTheme.fontXl
                color: ClassroomTheme.textSecondary
            }
            Text {
                Layout.alignment: Qt.AlignHCenter
                Layout.maximumWidth: 520
                text: classroom.coursesError || classroom.sourceNotice
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                font.family: ClassroomTheme.fontFamily
                font.pixelSize: ClassroomTheme.fontSm
                color: ClassroomTheme.textPlaceholder
            }
            Button {
                Layout.alignment: Qt.AlignHCenter
                text: "选择课程"
                enabled: classroom.courseCount > 0
                onClicked: root.requestCoursePicker()
            }
            Item { Layout.fillHeight: true }
        }

        ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: root.hasSlide
            clip: true
            contentWidth: availableWidth

            ColumnLayout {
                width: parent.width
                spacing: ClassroomTheme.spacingMd

                // cover
                Column {
                    Layout.fillWidth: true
                    spacing: ClassroomTheme.spacingSm
                    visible: root.isT("cover")
                    Text {
                        width: parent.width
                        text: root.s.title || ""
                        font.family: ClassroomTheme.fontFamily
                        font.pixelSize: ClassroomTheme.fontHero
                        font.bold: true
                        color: ClassroomTheme.text
                        wrapMode: Text.WordWrap
                    }
                    Text {
                        width: parent.width
                        text: root.s.subtitle || ""
                        font.family: ClassroomTheme.fontFamily
                        font.pixelSize: ClassroomTheme.fontLg
                        color: ClassroomTheme.textSecondary
                    }
                    Repeater {
                        model: root.isT("cover") ? (root.s.points || []) : []
                        Text {
                            required property var modelData
                            width: parent.width
                            text: "• " + modelData
                            font.family: ClassroomTheme.fontFamily
                            font.pixelSize: ClassroomTheme.fontMd
                            color: ClassroomTheme.text
                            wrapMode: Text.WordWrap
                        }
                    }
                }

                // vocab
                Column {
                    Layout.fillWidth: true
                    spacing: ClassroomTheme.spacingSm
                    visible: root.isT("vocab")
                    // 单词与 IPA 音标分为可自适应组件：宽屏同行、窄窗自动换行。
                    // 宽度取「自然宽（implicitWidth）与可用宽」的较小值：自然宽放得下时保持单行（宽屏排版不变），
                    // 放不下时收窄到可用宽并配合 WrapAnywhere 断行——无空格的长音标也能完整显示（含闭合斜杠），
                    // 不使用省略号或裁剪（CLASSROOM-V1-FIX-02）。
                    Flow {
                        id: wordIpaFlow
                        width: parent.width
                        spacing: ClassroomTheme.spacingLg
                        Text {
                            id: vocabWord
                            text: root.s.word || ""
                            font.family: ClassroomTheme.fontFamily
                            font.pixelSize: ClassroomTheme.fontHero
                            font.bold: true
                            color: ClassroomTheme.primary
                            width: Math.min(implicitWidth, wordIpaFlow.width)
                            wrapMode: Text.WrapAnywhere
                        }
                        Text {
                            id: vocabIpa
                            text: root.s.phonetic || ""
                            font.family: ClassroomTheme.fontFamily
                            font.pixelSize: ClassroomTheme.fontHero
                            font.bold: true
                            color: ClassroomTheme.primary
                            width: Math.min(implicitWidth, wordIpaFlow.width)
                            wrapMode: Text.WrapAnywhere
                        }
                    }
                    Text {
                        width: parent.width
                        visible: root.isT("vocab") && !(root.s.phonetic || "").length
                        text: "暂无音标（课件未提供，不编造；未标注口音）"
                        font.family: ClassroomTheme.fontFamily
                        font.pixelSize: ClassroomTheme.fontSm
                        color: ClassroomTheme.textPlaceholder
                    }
                    Text {
                        text: "释义：" + (root.s.meaning || "")
                        font.family: ClassroomTheme.fontFamily
                        font.pixelSize: ClassroomTheme.fontXl
                        color: ClassroomTheme.text
                    }
                    Rectangle { width: parent.width; height: 1; color: ClassroomTheme.border }
                    Text {
                        width: parent.width
                        text: root.s.en || ""
                        font.family: ClassroomTheme.fontFamily
                        font.pixelSize: ClassroomTheme.fontXl
                        color: ClassroomTheme.text
                        wrapMode: Text.WordWrap
                    }
                    Text {
                        width: parent.width
                        text: root.s.cn || ""
                        font.family: ClassroomTheme.fontFamily
                        font.pixelSize: ClassroomTheme.fontLg
                        color: ClassroomTheme.textSecondary
                        wrapMode: Text.WordWrap
                    }
                }

                // sentence
                Column {
                    Layout.fillWidth: true
                    spacing: ClassroomTheme.spacingSm
                    visible: root.isT("sentence")
                    Text {
                        width: parent.width
                        text: root.s.en || ""
                        font.family: ClassroomTheme.fontFamily
                        font.pixelSize: ClassroomTheme.fontHero - 6
                        color: ClassroomTheme.text
                        wrapMode: Text.WordWrap
                    }
                    Text {
                        width: parent.width
                        text: root.s.cn || ""
                        font.family: ClassroomTheme.fontFamily
                        font.pixelSize: ClassroomTheme.fontXl
                        color: ClassroomTheme.textSecondary
                        wrapMode: Text.WordWrap
                    }
                    Text {
                        width: parent.width
                        visible: !!root.s.note
                        text: "提示：" + (root.s.note || "")
                        font.family: ClassroomTheme.fontFamily
                        font.pixelSize: ClassroomTheme.fontMd
                        color: ClassroomTheme.warn
                        wrapMode: Text.WordWrap
                    }
                }

                // practice
                Column {
                    Layout.fillWidth: true
                    spacing: ClassroomTheme.spacingSm
                    visible: root.isT("practice")
                    Text {
                        width: parent.width
                        text: "随堂练习（本题无音频，为文本选择题，不构成听力测试）"
                        font.family: ClassroomTheme.fontFamily
                        font.pixelSize: ClassroomTheme.fontSm
                        color: ClassroomTheme.warn
                    }
                    Text {
                        width: parent.width
                        text: root.s.question || ""
                        font.family: ClassroomTheme.fontFamily
                        font.pixelSize: ClassroomTheme.fontXl
                        font.bold: true
                        color: ClassroomTheme.text
                        wrapMode: Text.WordWrap
                    }
                    Repeater {
                        model: root.isT("practice") ? (root.s.options || []) : []
                        Rectangle {
                            required property var modelData
                            required property int index
                            width: parent.width
                            height: 46
                            radius: ClassroomTheme.radiusMd
                            property bool answered: classroom.practice.answered === true
                            property bool picked: classroom.practice.picked === index
                            property bool isAnswer: index === root.s.answer
                            color: !answered ? ClassroomTheme.surfaceAlt
                                 : (isAnswer ? Qt.rgba(31/255,157/255,99/255,0.18)
                                    : (picked ? Qt.rgba(217/255,70/255,63/255,0.14)
                                       : ClassroomTheme.surfaceAlt))
                            border.width: 1
                            border.color: answered && (isAnswer || picked) ? ClassroomTheme.border : ClassroomTheme.border
                            Text {
                                anchors.verticalCenter: parent.verticalCenter
                                anchors.left: parent.left
                                anchors.leftMargin: ClassroomTheme.spacingMd
                                text: String.fromCharCode(65 + index) + ". " + modelData
                                font.family: ClassroomTheme.fontFamily
                                font.pixelSize: ClassroomTheme.fontMd
                                color: ClassroomTheme.text
                            }
                            MouseArea {
                                anchors.fill: parent
                                enabled: !classroom.practice.answered
                                cursorShape: Qt.PointingHandCursor
                                onClicked: classroom.answerPractice(index)
                            }
                        }
                    }
                    Text {
                        width: parent.width
                        visible: classroom.practice.answered === true
                        text: classroom.practice.feedback
                        color: classroom.practice.correct ? ClassroomTheme.success : ClassroomTheme.warn
                        font.family: ClassroomTheme.fontFamily
                        font.pixelSize: ClassroomTheme.fontMd
                        wrapMode: Text.WordWrap
                    }
                    // P2-8：答错后明确提供「再试一次」（错题仍保留在复习记录中）
                    Button {
                        visible: classroom.practice.answered === true
                                 && classroom.practice.graded === true
                                 && classroom.practice.correct === false
                        text: "再试一次"
                        onClicked: classroom.retryPractice()
                    }
                }

                // summary
                Column {
                    Layout.fillWidth: true
                    spacing: ClassroomTheme.spacingSm
                    visible: root.isT("summary")
                    Text {
                        text: root.s.title || "本课小结"
                        font.family: ClassroomTheme.fontFamily
                        font.pixelSize: ClassroomTheme.fontXl
                        font.bold: true
                        color: ClassroomTheme.text
                    }
                    Repeater {
                        model: root.isT("summary") ? (root.s.points || []) : []
                        Text {
                            required property var modelData
                            width: parent.width
                            text: "• " + modelData
                            font.family: ClassroomTheme.fontFamily
                            font.pixelSize: ClassroomTheme.fontMd
                            color: ClassroomTheme.text
                            wrapMode: Text.WordWrap
                        }
                    }
                }

                // 未知 slide.type —— 防御性兜底（绝不静默空白）
                // 权威路径：整包 fail-closed 拒绝（course_schema.validate_bundle →
                // classroom_model.coursesError），因此本分支在 v1 中**结构上不可达**；
                // 保留它是为了在"校验被绕过 / 未来版本前向兼容"时仍给出可见原因。
                Column {
                    Layout.fillWidth: true
                    spacing: ClassroomTheme.spacingSm
                    visible: root.slideTypeUnknown
                    Text {
                        width: parent.width
                        text: "未知内容类型（type=" + (root.s ? String(root.s.type) : "") + "）"
                        font.family: ClassroomTheme.fontFamily
                        font.pixelSize: ClassroomTheme.fontLg
                        font.bold: true
                        color: ClassroomTheme.warn
                        wrapMode: Text.WordWrap
                    }
                    Text {
                        width: parent.width
                        text: "该内容类型不被当前版本支持，未渲染任何内容（不显示空白页）。"
                        font.family: ClassroomTheme.fontFamily
                        font.pixelSize: ClassroomTheme.fontSm
                        color: ClassroomTheme.textSecondary
                        wrapMode: Text.WordWrap
                    }
                }
            }
        }

        // 课件导航
        RowLayout {
            Layout.fillWidth: true
            spacing: ClassroomTheme.spacingSm
            Text {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                elide: Text.ElideRight
                text: classroom.currentStepLabel
                font.family: ClassroomTheme.fontFamily
                font.pixelSize: ClassroomTheme.fontSm
                color: ClassroomTheme.textSecondary
            }
            Button { text: "上一页"; enabled: classroom.slideIndex > 0; onClicked: classroom.prevSlide() }
            Button { text: "重复讲解"; enabled: root.hasSlide && classroom.started; onClicked: classroom.repeatSlide() }
            Button {
                text: "下一页"
                enabled: classroom.slideIndex >= 0 && classroom.slideIndex + 1 < classroom.slideCount
                onClicked: classroom.nextSlide()
            }
        }
    }
}
