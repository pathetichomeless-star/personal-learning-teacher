import QtQuick
import QtWebEngine

/* 数字人 Live2D 组件（阶段 2）：QtWebEngineView 经回环 HTTP 加载 avatar_page.html
 * （D12 整改：file:// 下 QtWebEngine 阻断 file→file XHR（CORS），motion 资源
 * 加载失败 → 改由 Python 侧 AvatarRuntimeServer（127.0.0.1 ephemeral 静态服务器，
 * context property `avatarRuntime` 注入）承载，与实验室验证通道一致），
 * 绑定 VisionBridge 的 mouthLevel / avatarState 属性变化 → runJavaScript
 * 调用页面 __avatarAPI（12.5Hz 口型推送；mouthLevel=0 时 setMouthOpen(0)，
 * onTtsStop/onInterrupted 的归零语义由 bridge 属性自然带出）。
 *
 * 回退语义：runtime 服务器缺席 / 页面加载失败或 3 秒内无 modelInfo 回报 →
 * statusText 置 "Live2D 运行时不可用，已回退"（由 VisionPanel 转显）。
 * 生命周期：onCompleted 对 avatarRuntime.acquire()（启动服务器），
 * onDestruction release()（计数归零即 shutdown）+ destroyInstance + profile 清理。
 */
Rectangle {
    id: root
    property string avatarState: "idle"
    property real mouthLevel: 0.0
    property string statusText: "Live2D 运行时加载中…"
    property bool runtimeReady: false

    color: "#0b111a"; radius: 10

    // runtime 服务器经 context property `avatarRuntime` 注入（manager.start）；
    // 缺席（未注入/已停止）→ runtimeUrl 为空 → WebEngineView 停留 about:blank，
    // readyProbe 超时走"不可用，已回退"分支
    readonly property bool runtimeAvailable:
        typeof avatarRuntime !== "undefined" && avatarRuntime !== null
        && avatarRuntime.url && avatarRuntime.url.length > 0
    readonly property string runtimeUrl:
        runtimeAvailable ? avatarRuntime.url + "/avatar_page.html" : ""

    onRuntimeUrlChanged: {
        if (runtimeUrl.length > 0) { runtimeReady = false; readyProbe.restart() }
    }

    Component.onCompleted: {
        if (typeof avatarRuntime !== "undefined" && avatarRuntime !== null)
            avatarRuntime.acquire()   // 首引用即启动（端口/URL 就绪后绑定生效）
    }

    WebEngineView {
        id: webView
        anchors.fill: parent
        url: root.runtimeUrl.length > 0 ? root.runtimeUrl : "about:blank"
        // 页面为 http://127.0.0.1 同源 XHR，无需放开本地文件互访（暴露面最小化）
        settings.localContentCanAccessRemoteUrls: false
        settings.showScrollBars: false

        onRenderProcessTerminated: function (status, code) {
            root.statusText = "Live2D 运行时不可用，已回退"
        }
        onLoadingChanged: function (loadRequest) {
            if (loadRequest.status === WebEngineLoadingInfo.LoadFailedStatus) {
                root.statusText = "Live2D 运行时不可用，已回退"
            }
        }
    }

    // modelInfo 轮询判活：ready → 置位并同步 bridge 状态；
    // 页面无报错时宽容加载慢（XHR+解析可超 3s），累计 ~12s 或页面 ERROR 才判不可用
    property int probeAttempts: 0
    Timer {
        id: readyProbe
        interval: 1000
        repeat: true
        running: root.runtimeUrl.length > 0
        triggeredOnStart: true
        onTriggered: {
            if (root.runtimeReady) { stop(); return }
            root.probeAttempts++
            webView.runJavaScript(
                "JSON.stringify({r:(window.__avatarAPI ? __avatarAPI.modelInfo().ready : false),"
                + "e:(window.__avatarError || (window.__errors||[]).join(';'))})",
                function (s) {
                    var st = {}
                    try { st = JSON.parse(s) } catch (e2) {}
                    if (st.r) {
                        webView.runJavaScript("__avatarAPI.modelInfo()", function (info) {
                            root.runtimeReady = true
                            root.statusText = "Live2D · " + (info.id || "Hiyori")
                            root.pushCurrentState()
                        })
                        stop()
                    } else if (st.e || root.probeAttempts >= 10) {
                        root.statusText = "Live2D 运行时不可用，已回退"
                    }
                })
        }
    }

    // ---- bridge 属性 → 页面参数（12.5Hz 口型由 bridge 包络节拍保证） ----
    function pushCurrentState() {
        if (!root.runtimeReady) return
        webView.runJavaScript("__avatarAPI.setMouthOpen(" + Number(root.mouthLevel) + ")")
        webView.runJavaScript("__avatarAPI.setState(" + JSON.stringify(root.avatarState) + ")")
    }
    onMouthLevelChanged: {
        if (!root.runtimeReady) return
        webView.runJavaScript("__avatarAPI.setMouthOpen(" + Number(root.mouthLevel) + ")")
    }
    onAvatarStateChanged: {
        if (!root.runtimeReady) return
        webView.runJavaScript("__avatarAPI.setState(" + JSON.stringify(root.avatarState) + ")")
    }

    Text {
        id: fallbackLabel
        anchors.centerIn: parent
        width: parent.width - 24
        text: root.statusText
        color: root.runtimeReady ? "#93a4b5" : "#e8b53a"
        font.pixelSize: 12
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.Wrap
        visible: !root.runtimeReady || root.statusText.indexOf("Live2D ·") !== 0
        z: 10
    }

    Component.onDestruction: {
        // 资源释放（验收 f 通路）：页面销毁 WebGL 上下文 + profile 缓存清理
        try { webView.stop() } catch (e) {}
        try { webView.runJavaScript("__avatarAPI.destroyInstance()") } catch (e) {}
        try { webView.profile.clearHttpCache() } catch (e) {}
        // 生命周期与组件绑定：最后一个组件销毁即 shutdown 服务器线程
        if (typeof avatarRuntime !== "undefined" && avatarRuntime !== null)
            avatarRuntime.release()
    }
}
