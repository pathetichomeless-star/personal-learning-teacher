import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

/* 视觉面板（V1.0）：开关/相机说明/提交状态/数字人画布 —— 全部默认关闭。 */
Rectangle {
    id: root
    property var visionBridge: null
    // 数字人引擎（由 MainWindow 从注入的 context property 传入，规避同名遮蔽）
    property string avatarEngine: "canvas-fallback"
    color: "#17212e"; radius: 10
    implicitHeight: 320

    Component {
        id: live2dComp
        AvatarLive2D {
            anchors.fill: parent
            avatarState: root.visionBridge ? root.visionBridge.avatarState : "idle"
            mouthLevel: root.visionBridge ? root.visionBridge.mouthLevel : 0
        }
    }
    Component {
        id: canvasComp
        AvatarCanvas {
            anchors.fill: parent
            avatarState: root.visionBridge ? root.visionBridge.avatarState : "idle"
            mouthLevel: root.visionBridge ? root.visionBridge.mouthLevel : 0
        }
    }

    ColumnLayout {
        anchors.fill: parent; anchors.margins: 12; spacing: 8
        Label { text: "视觉 · 数字人（V1.0 原型）"; font.bold: true }
        RowLayout {
            Switch {
                id: enableSwitch
                text: "启用视觉"
                checked: root.visionBridge ? root.visionBridge.visionEnabled : false
                onToggled: if (root.visionBridge) root.visionBridge.setEnabled(checked)
            }
            Label { text: root.visionBridge ? root.visionBridge.visionStatus : "视觉关闭" }
        }
        RowLayout {
            Button {
                text: "让小智看看（测试图）"
                enabled: root.visionBridge && root.visionBridge.visionEnabled
                onClicked: if (root.visionBridge) root.visionBridge.submitImagePath(
                               "/tmp/vision_test.jpg")
            }
            Label { text: "摄像头单帧：V1.1（需 TCC 验收）"; color: "#93a4b5" }
        }
        // 数字人引擎分支：live2d → WebEngine Live2D；否则 Canvas 回退
        // （Canvas 不做渲染功能扩展——D6 静止缺陷仅记录不修）
        Loader {
            Layout.fillWidth: true
            Layout.preferredHeight: 260
            active: root.avatarEngine === "live2d"
            sourceComponent: live2dComp
        }
        Loader {
            Layout.fillWidth: true
            Layout.preferredHeight: 260
            active: root.avatarEngine !== "live2d"
            sourceComponent: canvasComp
        }
        Label {
            visible: root.avatarEngine !== "live2d"
            text: "Canvas 回退"
            color: "#e8b53a"; font.pixelSize: 12
        }
        Label {
            text: "MOCK/原型说明：口型为协议包络近似；真实逐样本 RMS 需冻结链路豁免。"
            color: "#e8b53a"; font.pixelSize: 12; wrapMode: Text.Wrap; Layout.fillWidth: true
        }
    }
}
