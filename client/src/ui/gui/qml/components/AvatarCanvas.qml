import QtQuick

/* 数字人 Canvas（V1.0）：分层 2D 动漫教师（Live2D 风格参数驱动 rig）。
 * 属性由 VisionBridge 驱动：state/mouthLevel。眨眼 2-5s 随机；打断/停止立即闭嘴。 */
Canvas {
    id: root
    property string avatarState: "idle"
    property real mouthLevel: 0.0
    property bool eyesClosed: false
    property real blinkNext: 0
    readonly property bool speaking: avatarState === "speaking"

    onAvatarStateChanged: requestPaint()
    onMouthLevelChanged: requestPaint()
    onPaint: {
        var ctx = getContext("2d")
        var now = new Date().getTime()
        if (blinkNext === 0) blinkNext = now + 2000 + Math.random() * 3000
        eyesClosed = now >= blinkNext && now < blinkNext + 150
        if (now >= blinkNext + 150) blinkNext = now + 2000 + Math.random() * 3000
        ctx.reset()
        var cx = width / 2, cy = height / 2
        ctx.fillStyle = "#0b111a"; ctx.fillRect(0, 0, width, height)
        /* 身体/服装 */
        ctx.fillStyle = "#2e4a6b"
        ctx.beginPath(); ctx.ellipse(cx, height - 10, width * 0.42, 90, 0, 0, Math.PI * 2); ctx.fill()
        ctx.fillStyle = "#e8eef5"
        ctx.beginPath(); ctx.moveTo(cx - 26, height - 96); ctx.lineTo(cx + 26, height - 96)
        ctx.lineTo(cx + 12, height - 14); ctx.lineTo(cx - 12, height - 14); ctx.fill()
        /* 脖子/头 */
        ctx.fillStyle = "#f2d3b3"
        ctx.fillRect(cx - 18, cy + 42, 36, 40)
        ctx.beginPath(); ctx.ellipse(cx, cy, 92, 108, 0, 0, Math.PI * 2); ctx.fill()
        /* 头发（后层 + 前层刘海） */
        ctx.fillStyle = "#3b3b52"
        ctx.beginPath(); ctx.ellipse(cx, cy - 30, 100, 96, 0, 0, Math.PI * 2); ctx.fill()
        ctx.beginPath(); ctx.ellipse(cx, cy - 52, 98, 66, 0, Math.PI, Math.PI * 2); ctx.fill()
        /* 眼睛 */
        var eyeH = eyesClosed ? 2 : 13
        ctx.fillStyle = "#1d2733"
        ctx.beginPath(); ctx.ellipse(cx - 36, cy - 14, 10, eyeH, 0, 0, Math.PI * 2); ctx.fill()
        ctx.beginPath(); ctx.ellipse(cx + 36, cy - 14, 10, eyeH, 0, 0, Math.PI * 2); ctx.fill()
        ctx.fillStyle = "#5b8dd9"
        if (!eyesClosed) {
            ctx.beginPath(); ctx.ellipse(cx - 36, cy - 14, 5, 6, 0, 0, Math.PI * 2); ctx.fill()
            ctx.beginPath(); ctx.ellipse(cx + 36, cy - 14, 5, 6, 0, 0, Math.PI * 2); ctx.fill()
        }
        /* 眉毛（speaking 微挑） */
        ctx.strokeStyle = "#3b3b52"; ctx.lineWidth = 3
        ctx.beginPath(); ctx.moveTo(cx - 48, cy - 34 - (speaking ? 3 : 0)); ctx.lineTo(cx - 24, cy - 37 - (speaking ? 3 : 0)); ctx.stroke()
        ctx.beginPath(); ctx.moveTo(cx + 24, cy - 37 - (speaking ? 3 : 0)); ctx.lineTo(cx + 48, cy - 34 - (speaking ? 3 : 0)); ctx.stroke()
        /* 腮红 */
        ctx.fillStyle = "#f0a8a0"
        ctx.beginPath(); ctx.ellipse(cx - 55, cy + 12, 12, 7, 0, 0, Math.PI * 2); ctx.fill()
        ctx.beginPath(); ctx.ellipse(cx + 55, cy + 12, 12, 7, 0, 0, Math.PI * 2); ctx.fill()
        /* 嘴（speaking 随 mouthLevel 开合；其余按状态微笑/平线） */
        if (speaking && mouthLevel > 0.03) {
            ctx.fillStyle = "#7a3f43"
            ctx.beginPath()
            ctx.ellipse(cx, cy + 40, 12 + mouthLevel * 11, 3 + mouthLevel * 16, 0, 0, Math.PI * 2)
            ctx.fill()
            ctx.fillStyle = "#e8a0a0"
            ctx.beginPath()
            ctx.ellipse(cx, cy + 44 + mouthLevel * 8, 7, 3 + mouthLevel * 5, 0, 0, Math.PI * 2)
            ctx.fill()
        } else {
            ctx.strokeStyle = "#7a3f43"; ctx.lineWidth = 3; ctx.beginPath()
            if (avatarState === "listening" || speaking)
                ctx.arc(cx, cy + 32, 34, 0.2 * Math.PI, 0.8 * Math.PI)
            else { ctx.moveTo(cx - 24, cy + 40); ctx.lineTo(cx + 24, cy + 40) }
            ctx.stroke()
        }
        /* 状态角标 */
        ctx.fillStyle = "#93a4b5"; ctx.font = "12px sans-serif"
        ctx.fillText("state=" + avatarState + (speaking ? " · speaking" : ""), 12, height - 12)
    }
    Timer {
        interval: 80; running: root.visible; repeat: true
        onTriggered: root.requestPaint()
    }
}
