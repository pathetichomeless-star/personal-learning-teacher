import QtQuick
import QtQuick.Window
import QtQuick.Controls
import QtQuick.Layouts
import "theme"

// XIAOZHI V4 学生课堂 V2 — 书库 / 导入 / 校对 / 发布 / 课堂（REV1B 画布落地）
// 保留 V1 的响应式与既有交互；新增栏目由左侧导航条切换。
ApplicationWindow {
    id: win
    title: "小智 AI 学生课堂"
    width: 1360
    height: 850
    minimumWidth: 560
    minimumHeight: 480
    visible: true
    color: ClassroomTheme.bg
    background: Rectangle { color: ClassroomTheme.bg }

    // 显式浅色调色板：Basic 样式下 TextField / Button / Dialog 背景取系统调色板，
    // 在深色模式下会与 ClassroomTheme 的深色文字叠加成"黑底黑字"（不可读）。
    // 这里把整个窗口（含全部 Popup）统一到浅色主题。
    palette.window: ClassroomTheme.bg
    palette.windowText: ClassroomTheme.text
    palette.base: ClassroomTheme.surface
    palette.alternateBase: ClassroomTheme.surfaceAlt
    palette.text: ClassroomTheme.text
    palette.placeholderText: ClassroomTheme.textPlaceholder
    palette.button: ClassroomTheme.surface
    palette.buttonText: ClassroomTheme.text
    palette.highlight: ClassroomTheme.primary
    palette.highlightedText: "#ffffff"
    palette.toolTipBase: ClassroomTheme.surface
    palette.toolTipText: ClassroomTheme.text
    palette.mid: ClassroomTheme.border
    palette.light: ClassroomTheme.surface
    palette.dark: ClassroomTheme.border

    property bool fullscreen: false
    visibility: fullscreen ? Window.FullScreen : Window.Windowed

    // BUILD4-EXIT-FIX-01：退出确认状态——确认弹窗点「退出」后置 true，
    // onClosing 据此放行真正的窗口关闭（关闭 → quitOnLastWindowClosed → 退出）。
    property bool quitConfirmed: false

    // R2-2：系统关闭路径（⌘W / 红叉）统一拦截，记录事件并走确认弹窗，防误触退出。
    // BUILD4-EXIT-FIX-01：已确认（quitConfirmed）时直接放行，避免「确认后仍被拦」死循环。
    onClosing: {
        if (win.quitConfirmed) {
            close.accepted = true
            return
        }
        close.accepted = false
        classroom.logWindowClose()
        quitConfirmDialog.open()
    }

    // 响应式断点
    readonly property string layoutMode:
        width >= 1180 ? "wide" :
        (width >= 900 ? "medium" :
         (width >= 640 ? "compact" : "narrow"))
    readonly property bool wideMode: layoutMode === "wide"
    readonly property bool medMode: layoutMode === "medium"
    readonly property bool compactMode: layoutMode === "compact"
    readonly property bool narrowMode: layoutMode === "narrow"

    // 当前栏目是否「课堂」页（决定底部学习操作栏是否显示）
    readonly property bool onClassroom: classroom.page === "classroom"

    function pageIndexOf(key) {
        var ps = classroom.pages
        for (var i = 0; i < ps.length; i++) {
            if (ps[i].key === key) return i
        }
        return 0
    }

    // 让测试/自动化可读
    readonly property string classroomWindowMode: layoutMode

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // ---------------------------------------------------------------- 顶部栏
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 62
            color: ClassroomTheme.surface
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: ClassroomTheme.border }

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: ClassroomTheme.spacingLg
                anchors.rightMargin: ClassroomTheme.spacingLg
                spacing: ClassroomTheme.spacingMd

                Text {
                    text: "小智 AI 学生课堂"
                    font.family: ClassroomTheme.fontFamily
                    font.pixelSize: ClassroomTheme.fontLg
                    font.bold: true
                    color: ClassroomTheme.text
                }
                Rectangle {
                    radius: 999
                    visible: !win.narrowMode
                    implicitWidth: modeT.implicitWidth + 16
                    implicitHeight: modeT.implicitHeight + 6
                    color: ClassroomTheme.primarySoft
                    Text {
                        id: modeT
                        anchors.centerIn: parent
                        text: "演示模式 · " + classroom.modeLabel
                        font.family: ClassroomTheme.fontFamily
                        font.pixelSize: ClassroomTheme.fontXs
                        color: ClassroomTheme.primary
                    }
                }
                Text {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    elide: Text.ElideRight
                    text: "老师：%1    ｜    课程：%2    ｜    %3    ｜    %4"
                        .arg(classroom.selectedTeacherName)
                        .arg(classroom.currentCourseTitle || "未选择")
                        .arg(classroom.currentLessonTitle || "未选择课时")
                        .arg(classroom.status)
                    font.family: ClassroomTheme.fontFamily
                    font.pixelSize: ClassroomTheme.fontSm
                    color: ClassroomTheme.textSecondary
                }
                Button {
                    text: win.fullscreen ? "退出全屏" : "全屏"
                    onClicked: win.fullscreen = !win.fullscreen
                }
                Button {
                    visible: win.wideMode || win.medMode
                    text: "高级设置"
                    onClicked: advancedDialog.open()
                }
                Button {
                    visible: win.wideMode || win.medMode
                    text: "退出课堂"
                    // R2-2：退出为显式请求——先确认防误触，确认后由 aboutToQuit 记录退出
                    onClicked: {
                        classroom.logExitRequested("button")
                        quitConfirmDialog.open()
                    }
                }
                // 紧凑/窄窗：次级入口折叠为「更多」菜单（避免越界遮挡）
                Button {
                    visible: win.compactMode || win.narrowMode
                    text: "更多"
                    onClicked: topMoreMenu.popup()
                    Menu {
                        id: topMoreMenu
                        MenuItem { text: "高级设置"; onTriggered: advancedDialog.open() }
                        MenuItem {
                            text: "退出课堂"
                            onTriggered: {
                                classroom.logExitRequested("menu")
                                quitConfirmDialog.open()
                            }
                        }
                    }
                }
            }
        }

        // -------------------------------------------------------------- 导航条
        NavBar { Layout.fillWidth: true }

        // ---------------------------------------------------------------- 页面栈
        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: win.pageIndexOf(classroom.page)

            // ---- 0. 课堂 ----
            RowLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.margins: ClassroomTheme.spacingMd
                spacing: ClassroomTheme.spacingMd

                // 左：老师
                TeacherPanel {
                    visible: win.layoutMode === "wide" || win.layoutMode === "medium"
                    Layout.fillHeight: true
                    Layout.preferredWidth: win.layoutMode === "wide" ? 260 : 210
                    onChangeTeacherRequested: teacherDialog.open()
                }

                // 紧凑/窄窗：左侧老师条（窄窗 96px，保证课件区始终可见）
                Rectangle {
                    visible: win.compactMode || win.narrowMode
                    Layout.fillHeight: true
                    Layout.preferredWidth: win.compactMode ? 104 : 96
                    radius: ClassroomTheme.radiusLg
                    color: ClassroomTheme.surface
                    border.width: 1
                    border.color: ClassroomTheme.border
                    ColumnLayout {
                        anchors.centerIn: parent
                        width: parent.width - 16
                        spacing: 2
                        TeacherAvatar {
                            Layout.alignment: Qt.AlignHCenter
                            Layout.preferredWidth: win.compactMode ? 64 : 40
                            Layout.preferredHeight: win.compactMode ? 64 : 40
                            showHint: false
                            teacherName: classroom.selectedTeacherName
                        }
                        Text {
                            Layout.fillWidth: true
                            horizontalAlignment: Text.AlignHCenter
                            text: classroom.selectedTeacherName
                            elide: Text.ElideRight
                            font.family: ClassroomTheme.fontFamily
                            font.pixelSize: ClassroomTheme.fontXs
                            color: ClassroomTheme.text
                        }
                        Button {
                            Layout.alignment: Qt.AlignHCenter
                            Layout.preferredWidth: Math.max(56, implicitContentWidth + 20)
                            Layout.preferredHeight: 26
                            text: "换老师"
                            onClicked: teacherDialog.open()
                        }
                    }
                }

                // 中：课件（始终最大）
                CourseArea {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.minimumWidth: 320
                    onRequestCoursePicker: courseDialog.open()
                }

                // 右：互动区（仅宽屏常驻）
                InteractionPanel {
                    visible: win.wideMode
                    Layout.fillHeight: true
                    Layout.preferredWidth: 330
                }
            }

            // ---- 1. 书库 ----
            LibraryPanel {}

            // ---- 2. 导入 ----
            ImportPanel {}

            // ---- 3. 校对 ----
            ProofreadPanel {}

            // ---- 4. 发布 ----
            PublishPanel {}
        }

        // ---------------------------------------------------------------- 底部栏
        // 仅「课堂」页显示学习操作；窄档把次级操作折叠进「更多」菜单，保证不越界、关键可达
        Rectangle {
            Layout.fillWidth: true
            visible: win.onClassroom
            implicitHeight: win.onClassroom ? 76 : 0
            color: ClassroomTheme.surface
            Rectangle { anchors.top: parent.top; width: parent.width; height: 1; color: ClassroomTheme.border }

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: ClassroomTheme.spacingLg
                anchors.rightMargin: ClassroomTheme.spacingLg
                spacing: ClassroomTheme.spacingSm

                Button {
                    text: "选择课程"
                    Layout.preferredWidth: Math.max(64, implicitContentWidth + 28)
                    onClicked: courseDialog.open()
                }
                Button {
                    text: "开始学习"
                    Layout.preferredWidth: Math.max(64, implicitContentWidth + 28)
                    highlighted: true
                    enabled: classroom.slideCount > 0 && !classroom.started
                    onClicked: classroom.startLearning()
                }

                TextField {
                    id: input
                    Layout.fillWidth: true
                    Layout.minimumWidth: (win.wideMode || win.medMode) ? 200 : 180
                    Layout.maximumWidth: 420
                    placeholderText: "输入你的答案或英文句子，回车提交"
                    onAccepted: { classroom.submitText(text); text = "" }
                }
                Button {
                    text: "提交"
                    Layout.preferredWidth: Math.max(64, implicitContentWidth + 28)
                    enabled: input.text.trim().length > 0
                    onClicked: { classroom.submitText(input.text); input.text = "" }
                }

                Button {
                    visible: win.wideMode
                    text: classroom.speechAvailable ? "语音对话" : "语音对话（不可用）"
                    Layout.preferredWidth: Math.max(64, implicitContentWidth + 28)
                    enabled: classroom.speechAvailable
                    ToolTip.visible: hovered
                    ToolTip.text: classroom.speechUnavailableReason
                }

                // 演练入口：与「语音对话（不可用）」并列且名称明确含「Mock」，
                // 不与真实语音能力混淆（见 DELIVERY-02 交付物 D）。
                Button {
                    text: "语音演练（Mock）"
                    Layout.preferredWidth: Math.max(64, implicitContentWidth + 28)
                    visible: win.wideMode || win.medMode
                    onClicked: voiceMockDialog.open()
                }

                Button {
                    text: "展开字幕"
                    Layout.preferredWidth: Math.max(64, implicitContentWidth + 28)
                    visible: win.medMode
                    onClicked: rightDrawer.open()
                }
                Button {
                    text: "重复讲解"
                    Layout.preferredWidth: Math.max(64, implicitContentWidth + 28)
                    visible: win.wideMode
                    enabled: classroom.started && classroom.slideCount > 0
                    onClicked: classroom.repeatSlide()
                }
                Button {
                    text: "下一页"
                    Layout.preferredWidth: Math.max(64, implicitContentWidth + 28)
                    visible: win.wideMode || win.medMode
                    enabled: classroom.slideCount > 0 && classroom.slideIndex + 1 < classroom.slideCount
                    onClicked: classroom.nextSlide()
                }
                Button {
                    text: "结束学习"
                    Layout.preferredWidth: Math.max(64, implicitContentWidth + 28)
                    visible: !win.narrowMode
                    onClicked: classroom.endLearning()
                }
                Button {
                    visible: !win.wideMode
                    text: "更多"
                    Layout.preferredWidth: Math.max(64, implicitContentWidth + 28)
                    onClicked: footerMoreMenu.popup()
                    Menu {
                        id: footerMoreMenu
                        MenuItem {
                            text: "语音对话（不可用：未接入真实实时语音）"
                            enabled: false
                            visible: !win.wideMode
                        }
                        MenuItem {
                            text: "语音演练（Mock）"
                            visible: !(win.wideMode || win.medMode)
                            onTriggered: voiceMockDialog.open()
                        }
                        MenuItem {
                            text: "重复讲解"
                            visible: !win.wideMode
                            enabled: classroom.started && classroom.slideCount > 0
                            onTriggered: classroom.repeatSlide()
                        }
                        MenuItem {
                            text: "展开字幕"
                            visible: win.compactMode || win.narrowMode
                            onTriggered: rightDrawer.open()
                        }
                        MenuSeparator { visible: win.narrowMode }
                        MenuItem {
                            text: "结束学习"
                            visible: win.narrowMode
                            onTriggered: classroom.endLearning()
                        }
                    }
                }
            }
        }
    }

    // 紧凑/中等窗口：字幕抽屉
    Drawer {
        id: rightDrawer
        edge: Qt.RightEdge
        width: Math.min(360, win.width - 80)
        height: win.height - 62 - 76
        y: 62
        modal: false
        InteractionPanel { anchors.fill: parent }
    }

    // ------------------------------------------------------------------ 弹窗
    Dialog {
        id: teacherDialog
        title: "选择 AI 老师"
        modal: true
        anchors.centerIn: parent
        width: Math.min(520, win.width - 40)
        standardButtons: Dialog.NoButton
        onOpened: { classroom.loadSelectedTeacher(); classroom.refreshTeachers() }

        contentItem: ColumnLayout {
            spacing: ClassroomTheme.spacingSm
            // P1-3：真实能力状态诚实化——静态「未」占位与空列表都是当前事实，不冒充
            Text {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                text: "当前状态：未接入真实 AI 老师（等待独立安全复核与授权）。"
                      + "数字人为静态占位、讲解为本地文字演示；正式版将支持选择老师、"
                      + "声音、教学语言、真实语音与数字人。"
                font.family: ClassroomTheme.fontFamily
                font.pixelSize: ClassroomTheme.fontXs
                color: ClassroomTheme.warn
            }
            Text {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                text: classroom.teachersState
                font.family: ClassroomTheme.fontFamily
                font.pixelSize: ClassroomTheme.fontSm
                color: ClassroomTheme.textSecondary
            }
            ListView {
                id: teacherList
                Layout.fillWidth: true
                // 同 courseDialog.lessonList：ListView 的 implicitWidth = contentWidth，
                // 不设 minimumWidth=0 会把弹窗撑宽（老师名/音色越长越明显）。
                Layout.minimumWidth: 0
                Layout.preferredWidth: 300
                Layout.preferredHeight: 220
                clip: true
                model: classroom.teachers
                spacing: 4
                delegate: Rectangle {
                    required property var modelData
                    width: parent.width
                    height: 46
                    radius: ClassroomTheme.radiusMd
                    color: classroom.selectedTeacherId === modelData.teacher_id
                           ? ClassroomTheme.primarySoft : ClassroomTheme.surfaceAlt
                    border.width: 1
                    border.color: classroom.selectedTeacherId === modelData.teacher_id
                                  ? ClassroomTheme.primary : ClassroomTheme.border
                    Column {
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.left: parent.left
                        anchors.leftMargin: ClassroomTheme.spacingMd
                        Text {
                            text: modelData.display_name || modelData.teacher_id
                            font.family: ClassroomTheme.fontFamily
                            font.pixelSize: ClassroomTheme.fontMd
                            color: ClassroomTheme.text
                        }
                        Text {
                            text: "教学语言 " + (modelData.language || "未提供") + " · 音色 " + (modelData.voice_id || "默认")
                            font.family: ClassroomTheme.fontFamily
                            font.pixelSize: ClassroomTheme.fontXs
                            color: ClassroomTheme.textSecondary
                        }
                    }
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: classroom.selectTeacher(modelData.teacher_id)
                    }
                }
            }
            Text {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                text: "部署令牌由隔离配置预置，学生无需填写，也不会在此显示。保存只更新老师选择，不会自动建立连接。"
                font.family: ClassroomTheme.fontFamily
                font.pixelSize: ClassroomTheme.fontXs
                color: ClassroomTheme.textPlaceholder
            }
            RowLayout {
                Layout.fillWidth: true
                Button { text: "刷新列表"; onClicked: classroom.refreshTeachers() }
                Item { Layout.fillWidth: true }
                Button { text: "取消"; onClicked: teacherDialog.close() }
                Button {
                    text: "保存并切换"
                    highlighted: true
                    // R2-6：无「有效、可选择」的老师时禁用（有效性=条目含非空 teacher_id，
                    // 不是仅列表非空），并给出明确中文说明。
                    enabled: classroom.teachers.filter(function (t) {
                        return String(t.teacher_id || "").length > 0
                    }).length > 0
                    onClicked: { classroom.saveTeacher(); teacherDialog.close() }
                }
            }
            // R2-6：无可选老师时的中文说明（与按钮 enabled 同条件显示）
            Text {
                Layout.fillWidth: true
                visible: classroom.teachers.filter(function (t) {
                    return String(t.teacher_id || "").length > 0
                }).length === 0
                wrapMode: Text.WordWrap
                text: "当前没有可选择老师，暂无法保存切换；可点「刷新列表」重试。"
                font.family: ClassroomTheme.fontFamily
                font.pixelSize: ClassroomTheme.fontXs
                color: ClassroomTheme.warn
            }
        }
    }

    Dialog {
        id: courseDialog
        title: "选择课程与课时"
        modal: true
        anchors.centerIn: parent
        width: Math.min(640, win.width - 40)
        standardButtons: Dialog.NoButton

        // 必须显式赋给 contentItem：直接声明的子项只是 contentItem 的普通子项，
        // 不会随弹窗宽度收缩（ColumnLayout 保持 implicitWidth），会溢出窗口。
        contentItem: ColumnLayout {
            spacing: ClassroomTheme.spacingSm
            RowLayout {
                Layout.fillWidth: true
                spacing: ClassroomTheme.spacingMd
                ListView {
                    id: courseList
                    Layout.preferredWidth: 280
                    Layout.minimumWidth: 0
                    Layout.maximumWidth: 280
                    Layout.preferredHeight: 260
                    clip: true
                    model: classroom.courses
                    spacing: 4
                    delegate: Rectangle {
                        required property var modelData
                        width: parent.width
                        height: 54
                        radius: ClassroomTheme.radiusMd
                        color: classroom.currentCourseIndex === modelData.index
                               ? ClassroomTheme.primarySoft : ClassroomTheme.surfaceAlt
                        border.width: 1
                        border.color: ClassroomTheme.border
                        Column {
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.left: parent.left
                            anchors.leftMargin: ClassroomTheme.spacingMd
                            Text {
                                text: modelData.title
                                font.family: ClassroomTheme.fontFamily
                                font.pixelSize: ClassroomTheme.fontMd
                                color: ClassroomTheme.text
                            }
                            Text {
                                text: (modelData.level || "") + " · " + (modelData.description || "")
                                font.family: ClassroomTheme.fontFamily
                                font.pixelSize: ClassroomTheme.fontXs
                                color: ClassroomTheme.textSecondary
                            }
                        }
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: classroom.selectCourse(modelData.index)
                        }
                    }
                }
            ListView {
                id: lessonList
                Layout.fillWidth: true
                // ListView.implicitWidth 来自 contentWidth（随委托文本增长），
                // 若不给 minimumWidth=0，RowLayout 会把宽度撑到 contentWidth，
                // 导致弹窗内容（含「进入课堂」）溢出窗口 —— 见 DELIVERY-02 页面探针 P08a。
                Layout.minimumWidth: 0
                Layout.preferredWidth: 280
                Layout.preferredHeight: 260
                clip: true
                model: classroom.lessons
                    spacing: 4
                    delegate: Rectangle {
                        required property var modelData
                        width: parent.width
                        height: 46
                        radius: ClassroomTheme.radiusMd
                        color: classroom.currentLessonIndex === modelData.index
                               ? ClassroomTheme.primarySoft : ClassroomTheme.surfaceAlt
                        border.width: 1
                        border.color: ClassroomTheme.border
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.left: parent.left
                            anchors.leftMargin: ClassroomTheme.spacingMd
                            text: modelData.title
                            font.family: ClassroomTheme.fontFamily
                            font.pixelSize: ClassroomTheme.fontSm
                            color: ClassroomTheme.text
                        }
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: classroom.selectLesson(modelData.index)
                        }
                    }
                }
            }
            Text {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                text: "来源：" + classroom.sourceLabel + "。" + classroom.sourceNotice
                font.family: ClassroomTheme.fontFamily
                font.pixelSize: ClassroomTheme.fontXs
                color: ClassroomTheme.textPlaceholder
            }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                Button {
                    text: "进入课堂"
                    highlighted: true
                    enabled: classroom.slideCount > 0
                    onClicked: courseDialog.close()
                }
            }
        }
    }

    Dialog {
        id: advancedDialog
        title: "高级设置（维护者）"
        modal: true
        anchors.centerIn: parent
        width: Math.min(520, win.width - 40)
        standardButtons: Dialog.NoButton
        contentItem: ColumnLayout {
            spacing: ClassroomTheme.spacingSm
            Text {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                // R2-8：按目标架构准确表述——正式管理后台部署于 NAS，演示课堂尚未
                // 完成与 NAS 的正式联调；不误称 NAS 已连接。
                text: "老师档案、模型与服务商、独立凭据、课程与知识库等管理功能，" +
                      "由管理后台统一维护：正式管理后台部署于 NAS，当前演示课堂" +
                      "尚未完成与 NAS 的正式联调。学生课堂只负责学习操作。"
                font.family: ClassroomTheme.fontFamily
                font.pixelSize: ClassroomTheme.fontSm
                color: ClassroomTheme.text
            }
            Text {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                text: "为保护学生日常使用，本界面不显示 WebSocket 地址、部署令牌或任何密钥字段。"
                font.family: ClassroomTheme.fontFamily
                font.pixelSize: ClassroomTheme.fontSm
                color: ClassroomTheme.textSecondary
            }
            Text {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                text: "语音状态：" + classroom.speechUnavailableReason
                font.family: ClassroomTheme.fontFamily
                font.pixelSize: ClassroomTheme.fontXs
                color: ClassroomTheme.textPlaceholder
            }
            // R2-8：以中文「关闭」替代 Qt 标准英文 Close 按钮
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                Button { text: "关闭"; onClicked: advancedDialog.close() }
            }
        }
    }

    // R2-2：退出确认弹窗（防误触；⌘W / 红叉 / 「退出课堂」均汇入此处）
    // BUILD4-EXIT-FIX-01：确认走 win.close() 放行路径（单次点击确定性退出）；
    // onClosed 复位 quitConfirmed，确保任何关闭弹窗的路径都不残留已确认状态。
    Dialog {
        id: quitConfirmDialog
        title: "退出课堂"
        modal: true
        anchors.centerIn: parent
        width: Math.min(420, win.width - 40)
        standardButtons: Dialog.NoButton
        onClosed: win.quitConfirmed = false
        contentItem: ColumnLayout {
            spacing: ClassroomTheme.spacingSm
            Text {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                text: "确定要退出小智课堂吗？学习进度与课堂笔记已自动保存。"
                font.family: ClassroomTheme.fontFamily
                font.pixelSize: ClassroomTheme.fontMd
                color: ClassroomTheme.text
            }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                // 取消退出：复位确认状态，应用保持运行
                Button {
                    text: "继续学习"
                    onClicked: {
                        win.quitConfirmed = false
                        quitConfirmDialog.close()
                    }
                }
                // 确认退出：置确认状态并关闭窗口（onClosing 放行 → 最后窗口关闭 → 应用退出）。
                // 历史教训（BUILD4-EXIT-DIAG-01）：此处原为 Qt.quit()，因引擎 quit 信号
                // 无接收者而静默失效；win.close() 走窗口关闭链，语义真实且可观测。
                Button {
                    text: "退出"
                    highlighted: true
                    onClicked: {
                        win.quitConfirmed = true
                        classroom.logExitConfirmed()
                        win.close()
                    }
                }
            }
        }
    }

    // ------------------------------------------------- 语音演练（Mock 双向对话）
    // 事件日志来自 VoiceMockSession 的真实事件流（非动画、非硬编码）。
    // 本对话框**不**产生真实语音、不联网、不调用模型。
    Dialog {
        id: voiceMockDialog
        title: "语音演练（Mock 双向对话）"
        modal: true
        anchors.centerIn: parent
        width: Math.min(720, win.width - 40)
        height: Math.min(600, win.height - 60)
        standardButtons: Dialog.NoButton

        contentItem: ColumnLayout {
            spacing: ClassroomTheme.spacingSm

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: bnr.implicitHeight + 20
                radius: ClassroomTheme.radiusMd
                color: Qt.rgba(217 / 255, 131 / 255, 23 / 255, 0.12)
                border.width: 1
                border.color: ClassroomTheme.warn
                Text {
                    id: bnr
                    anchors.fill: parent
                    anchors.margins: 10
                    wrapMode: Text.WordWrap
                    text: classroom.voiceMockBanner
                    font.family: ClassroomTheme.fontFamily
                    font.pixelSize: ClassroomTheme.fontSm
                    color: ClassroomTheme.text
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: ClassroomTheme.spacingMd
                Text {
                    text: "模式：" + classroom.voiceMockModeLabel
                    font.family: ClassroomTheme.fontFamily
                    font.pixelSize: ClassroomTheme.fontSm
                    color: ClassroomTheme.textSecondary
                }
                Text {
                    text: "会话状态：" + classroom.voiceMockState
                    font.family: ClassroomTheme.fontFamily
                    font.pixelSize: ClassroomTheme.fontSm
                    color: ClassroomTheme.textSecondary
                }
                Text {
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                    text: classroom.voiceMockTextOnly ? "音频：未采集（仅文字驱动）" : "音频：未采集"
                    font.family: ClassroomTheme.fontFamily
                    font.pixelSize: ClassroomTheme.fontXs
                    color: ClassroomTheme.textPlaceholder
                }
            }

            Text {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                visible: !classroom.voiceMockEnabled
                text: "演练未启用。启用后可在本机完成一轮「学生 → 老师」的模拟对话并留下事件日志。"
                font.family: ClassroomTheme.fontFamily
                font.pixelSize: ClassroomTheme.fontSm
                color: ClassroomTheme.textSecondary
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: ClassroomTheme.spacingSm
                Button {
                    text: classroom.voiceMockEnabled ? "重新开始演练" : "启用演练（Mock）"
                    onClicked: classroom.voiceMockEnabled ? classroom.voiceMockReset()
                                                          : classroom.voiceMockEnable()
                }
                Item { Layout.fillWidth: true }
                Button {
                    text: "关闭"
                    onClicked: voiceMockDialog.close()
                }
            }

            TextField {
                id: vmInput
                Layout.fillWidth: true
                enabled: classroom.voiceMockEnabled
                placeholderText: "输入学生在演练中要说的话，回车发送（不会发送到任何网络）"
                onAccepted: {
                    if (classroom.voiceMockEnabled) { classroom.voiceMockSend(text); text = "" }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: ClassroomTheme.spacingSm
                Button {
                    text: "发送（Mock）"
                    enabled: classroom.voiceMockEnabled && vmInput.text.trim().length > 0
                    onClicked: { classroom.voiceMockSend(vmInput.text); vmInput.text = "" }
                }
                Text {
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    text: classroom.voiceMockError
                    visible: classroom.voiceMockError.length > 0
                    font.family: ClassroomTheme.fontFamily
                    font.pixelSize: ClassroomTheme.fontXs
                    color: ClassroomTheme.danger
                }
            }

            Text {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                visible: classroom.voiceMockReply.length > 0
                text: "老师（Mock）：" + classroom.voiceMockReply
                font.family: ClassroomTheme.fontFamily
                font.pixelSize: ClassroomTheme.fontSm
                color: ClassroomTheme.text
            }

            Text {
                Layout.fillWidth: true
                text: "事件日志（真实事件流，共 " + classroom.voiceMockEventCount + " 条）"
                font.family: ClassroomTheme.fontFamily
                font.pixelSize: ClassroomTheme.fontSm
                font.bold: true
                color: ClassroomTheme.text
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: ClassroomTheme.radiusMd
                color: ClassroomTheme.surface
                border.width: 1
                border.color: ClassroomTheme.border

                ListView {
                    id: vmLogList
                    anchors.fill: parent
                    anchors.margins: 8
                    clip: true
                    spacing: 3
                    model: classroom.voiceMockEvents
                    Text {
                        anchors.fill: parent
                        visible: vmLogList.count === 0
                        wrapMode: Text.WordWrap
                        text: "（暂无事件：先启用演练并发送一轮消息）"
                        font.family: ClassroomTheme.fontFamily
                        font.pixelSize: ClassroomTheme.fontXs
                        color: ClassroomTheme.textPlaceholder
                    }
                    delegate: Rectangle {
                        id: vmLogRow
                        required property var modelData
                        required property int index
                        width: vmLogList.width
                        height: 42
                        radius: ClassroomTheme.radiusSm
                        color: ClassroomTheme.surfaceAlt
                        // P2-11：事件类型用中文业务名展示；原始技术细节保留在「诊断」行
                        //（事件日志同时是验收证据，不删除技术内容）
                        readonly property string typeLabel:
                            modelData.type === "final_transcript" ? "学生发言已确认"
                            : modelData.type === "teacher_speaking" ? "老师开始讲解"
                            : modelData.type === "teacher_done" ? "老师讲解完成"
                            : modelData.type === "error" ? "出错"
                            : String(modelData.type || "事件")
                        Column {
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.left: parent.left
                            anchors.leftMargin: ClassroomTheme.spacingSm
                            width: parent.width - 2 * ClassroomTheme.spacingSm
                            Text {
                                width: parent.width
                                elide: Text.ElideRight
                                text: (index + 1) + ". " + vmLogRow.typeLabel
                                      + ((modelData.text || modelData.reason) ? ("：" + (modelData.text || modelData.reason)) : "")
                                font.family: ClassroomTheme.fontFamily
                                font.pixelSize: ClassroomTheme.fontXs
                                color: modelData.type === "error"
                                       ? ClassroomTheme.danger : ClassroomTheme.text
                            }
                            Text {
                                width: parent.width
                                elide: Text.ElideRight
                                visible: modelData.code !== undefined || modelData.state !== undefined
                                text: "诊断：state=" + (modelData.state || "-")
                                      + (modelData.code !== undefined ? (" code=" + modelData.code) : "")
                                font.family: ClassroomTheme.fontFamily
                                font.pixelSize: ClassroomTheme.fontXs
                                color: ClassroomTheme.textPlaceholder
                            }
                        }
                    }
                }
            }
        }
    }
}
