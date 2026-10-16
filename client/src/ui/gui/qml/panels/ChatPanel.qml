// 对话面板（CLIENT-UI-1：学习者可见的双语气泡 + 状态 + 自动滚动）
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"

Rectangle {
    id: root

    color: Theme.background

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.spacingLg
        spacing: Theme.spacingMd

        // 对话气泡列表（user / assistant 双方文本；STREAMING / FINAL / INTERRUPTED）
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            radius: Theme.radiusMd
            color: Theme.backgroundSecondary

            ListView {
                id: chatList
                anchors.fill: parent
                anchors.margins: Theme.spacingMd
                clip: true
                spacing: Theme.spacingSm
                model: mainModel ? mainModel.transcriptItems : []
                onCountChanged: chatList.positionViewAtEnd()
                boundsBehavior: Flickable.StopAtBounds

                delegate: Rectangle {
                    required property var modelData
                    width: chatList.width
                    height: bubble.implicitHeight + Theme.spacingMd
                    radius: Theme.radiusMd
                    color: modelData.role === "user" ? Theme.background : Theme.backgroundSecondary
                    border.width: 1
                    border.color: Theme.backgroundSecondary

                    Text {
                        id: bubble
                        anchors.fill: parent
                        anchors.margins: Theme.spacingSm
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeMd
                        color: Theme.textPrimary
                        wrapMode: Text.Wrap
                        lineHeight: 1.45
                        text: {
                            var who = modelData.role === "user" ? "你" : "老师";
                            var body = modelData.text || "";
                            var tail = "";
                            if (modelData.state === "STREAMING") { tail = " …"; }
                            else if (modelData.state === "INTERRUPTED") { tail = "（已打断）"; }
                            return who + ": " + body + tail;
                        }
                    }
                }

                Text {
                    anchors.centerIn: parent
                    visible: chatList.count === 0
                    text: "等待对话..."
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeMd
                    color: Theme.textPlaceholder
                }
            }
        }

        // 音乐 / 歌词
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: hasMusic ? 48 : 0
            visible: hasMusic
            radius: Theme.radiusMd
            color: Theme.backgroundSecondary

            readonly property bool hasMusic: !!(mainModel && mainModel.musicLine
                                               && mainModel.musicLine.length > 0)

            Text {
                anchors.fill: parent
                anchors.margins: Theme.spacingSm
                text: (mainModel && mainModel.musicLine) ? mainModel.musicLine : ""
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeSm
                color: Theme.textPlaceholder
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                elide: Text.ElideRight
            }
        }
    }
}