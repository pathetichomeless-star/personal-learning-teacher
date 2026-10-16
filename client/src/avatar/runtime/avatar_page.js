/* avatar_page.js — 数字人 Live2D 运行时逻辑（阶段 2 集成版）。
 *
 * 改编自 prototypes/avatar-runtime-lab/app.js（阶段 1，17/17 断言通过）：
 *  - 保留 afterMotionUpdate 每帧参数覆盖通路（motion 更新后、coreModel.update 前
 *    写入 ParamMouthOpenY / ParamEyeLOpen / ParamAngleX...，外部值不被 idle 动作覆盖）；
 *  - 保留 __fitModel 小 scale 实测标定（人物逻辑尺寸远大于 canvasinfo 推算值，
 *    基于 model.width 的 fit 全部失准，见 lab README §7.3）；
 *  - 对外接口从 __avatarTestAPI 更名为 __avatarAPI，语义一致：
 *    setMouthOpen / setExpression / setState / setHead / setEyes /
 *    resetMouth / modelInfo / destroyInstance
 *    由 AvatarLive2D.qml 通过 runJavaScript 驱动（VisionBridge 12.5Hz 口型包络）。
 */
/* global PIXI, Live2DModel */
"use strict";

window.__errors = [];
window.addEventListener("error", function (e) {
  window.__errors.push(String(e.message || e));
});
window.addEventListener("unhandledrejection", function (e) {
  window.__errors.push("unhandledrejection: " + String(e.reason));
});

// ---- XHR 记录（D12 整改验证用：资源全部应经回环 HTTP 且零失败） ----
window.__xhrLog = [];
(function () {
  var xopen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (method, url) {
    var xhr = this;
    var entry = { url: String(url), status: 0, ok: false };
    window.__xhrLog.push(entry);
    this.addEventListener("loadend", function () {
      entry.status = xhr.status;
      entry.ok = xhr.status >= 200 && xhr.status < 300;
    });
    return xopen.apply(this, arguments);
  };
})();
function xhrFailures() {
  return window.__xhrLog.filter(function (e) { return !e.ok; }).length;
}

window.__avatarReady = false;   // fit 完成后置 true（QML 轮询 modelInfo 判活）
window.__avatarError = null;

var MODEL_URL = "vendor/models/Hiyori/Hiyori.model3.json";

// ---- 外部驱动状态（由 __avatarAPI 修改，每帧覆盖进 coreModel） ----
var external = {
  mouthOpen: 0.0,        // 0..1，对应 ParamMouthOpenY
  expression: "neutral", // 表情名（参数组合模拟，Hiyori 无 exp3 文件）
  state: "idle",         // idle/listening/thinking/speaking/interrupted
  head: { x: 0, y: 0, z: 0 }, // 头部角度（每帧覆盖，参数同 motion 写入时机）
  eyeOpen: 1.0,          // 双眼开合 0..1
};

// 表情 → 参数组合（Hiyori 没有 .exp3.json，用标准参数模拟，值域见 cdi3.json）
var EXPRESSIONS = {
  neutral: {},
  happy:   { ParamMouthForm: 1.0, ParamEyeLSmile: 0.8, ParamEyeRSmile: 0.8, ParamBrowLY: 0.3, ParamBrowRY: 0.3 },
  sad:     { ParamMouthForm: -1.0, ParamBrowLAngle: -1.0, ParamBrowRAngle: -1.0, ParamEyeLOpen: 0.5, ParamEyeROpen: 0.5 },
  angry:   { ParamMouthForm: -0.6, ParamBrowLY: -0.7, ParamBrowRY: -0.7, ParamBrowLForm: 0.1, ParamEyeLOpen: 0.9, ParamEyeROpen: 0.9 },
  surprised: { ParamEyeLOpen: 1.0, ParamEyeROpen: 1.0, ParamMouthOpenY: 0.6, ParamBrowLY: 1.0, ParamBrowRY: 1.0, ParamEyeBallY: 0.4 },
};

var model = null;
var wrapper = null;           // 普通容器：Live2DModel 自身 transform 不可靠（transform=null），
                              // fit 变换统一作用在 wrapper 上（lab 阶段 1 结论）
var app = null;
var overridesActive = true;   // 资源释放前置 false，避免销毁后仍写参数
var badge = document.getElementById("state-badge");

function clamp01(v) { return Math.min(1, Math.max(0, Number(v) || 0)); }
function clampNum(v, lo, hi) { v = Number(v); return Number.isFinite(v) ? Math.min(hi, Math.max(lo, v)) : lo; }

function coreModel() { return model && model.internalModel && model.internalModel.coreModel; }

function setParam(id, v) {
  var cm = coreModel();
  if (!cm) return false;
  cm.setParameterValueById(id, v);
  return true;
}

function getParam(id) {
  var cm = coreModel();
  if (!cm) return null;
  try { return cm.getParameterValueById(id); } catch (e) { return null; }
}

// 每帧覆盖：motion 更新之后、coreModel.update() 之前
function applyExternalParams() {
  if (!overridesActive || !model) return;
  var cm = coreModel();
  if (!cm) return;
  cm.setParameterValueById("ParamMouthOpenY", external.mouthOpen);
  var face = EXPRESSIONS[external.expression] || {};
  for (var id in face) cm.setParameterValueById(id, face[id]);
  cm.setParameterValueById("ParamAngleX", external.head.x);
  cm.setParameterValueById("ParamAngleY", external.head.y);
  cm.setParameterValueById("ParamAngleZ", external.head.z);
  cm.setParameterValueById("ParamEyeLOpen", external.eyeOpen);
  cm.setParameterValueById("ParamEyeROpen", external.eyeOpen);
  // 状态附加表现：thinking 时歪头叠加
  if (external.state === "thinking") cm.setParameterValueById("ParamAngleZ", external.head.z - 10);
}

function setBadge(text) { if (badge) badge.textContent = text; }

// 人物像素包围盒 + 像素校验和（背景色 0x101014，readPixels 原点左下→换算为左上原点坐标）
function readFrame() {
  var c = document.querySelector("#stage canvas");
  if (!c) return null;
  var gl = c.getContext("webgl2") || c.getContext("webgl") || c.getContext("experimental-webgl");
  if (!gl) return null;
  var w = gl.drawingBufferWidth, h = gl.drawingBufferHeight;
  var px = new Uint8Array(w * h * 4);
  gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, px);
  return { gl: gl, w: w, h: h, px: px };
}

function contentBBox() {
  var f = readFrame();
  if (!f) return null;
  var px = f.px, w = f.w, h = f.h;
  var x0 = w, x1 = 0, y0 = h, y1 = 0, found = false;
  for (var y = 0; y < h; y += 4) {
    for (var x = 0; x < w; x += 4) {
      var i = (y * w + x) * 4;
      if (Math.abs(px[i] - 16) > 10 || Math.abs(px[i + 1] - 16) > 10 || Math.abs(px[i + 2] - 20) > 12) {
        found = true;
        if (x < x0) x0 = x; if (x > x1) x1 = x;
        if (y < y0) y0 = y; if (y > y1) y1 = y;
      }
    }
  }
  if (!found) return null;
  return { x0: x0, x1: x1, y0: h - 1 - y1, y1: h - 1 - y0, w: w, h: h };
}

// 稀疏像素校验和（帧差分等价的低成本探针：有非背景像素变化即非零）
window.__pixelHash = function () {
  var f = readFrame();
  if (!f) return 0;
  var px = f.px, w = f.w, h = f.h, hash = 0, n = 0;
  for (var y = 0; y < h; y += 4) {
    for (var x = 0; x < w; x += 4) {
      var i = (y * w + x) * 4;
      if (Math.abs(px[i] - 16) > 10 || Math.abs(px[i + 1] - 16) > 10 || Math.abs(px[i + 2] - 20) > 12) {
        hash = (hash + px[i] * 31 + px[i + 1] * 17 + px[i + 2] * 7 + n) & 0x7fffffff;
        n++;
      }
    }
  }
  return hash;
};

function renderOnce() {
  if (!model || !app) return;
  try { model.update(1000 / 60); } catch (e) { /* 动作结束时可能抛 benign 错误 */ }
  app.render();
}

// 人物取景标定（lab 阶段 1 验证：小 scale 实测一次解出精确缩放/居中）
window.__fitModel = function () {
  if (!wrapper || !app) return false;
  var cx = app.screen.width / 2, cy = app.screen.height / 2;
  var s0 = 0.1;
  wrapper.scale.set(s0);
  wrapper.position.set(cx, cy);
  renderOnce();
  var bb = contentBBox();
  if (!bb || bb.y1 - bb.y0 < 4 || bb.x1 - bb.x0 < 4) return false;
  var h0 = (bb.y1 - bb.y0) / s0;              // 人物屏幕高（scale=1 当量）
  var mcx = ((bb.x0 + bb.x1) / 2 - cx) / s0;  // 人物中心（wrapper 坐标）
  var mcy = ((bb.y0 + bb.y1) / 2 - cy) / s0;
  var sFit = (app.screen.height * 0.92) / h0;
  wrapper.scale.set(sFit);
  wrapper.position.set(cx - mcx * sFit, cy - mcy * sFit);
  renderOnce();
  return true;
};

// fit 重试：客户端 WebEngineView 实际尺寸可能晚于页面初始化（D12 假设 2），
// 首次标定失败时按 250ms 间隔重试（上限 8 次）；resize/refit 时计数清零重开
var fitAttempts = 0;
function tryFit() {
  if (!window.__fitModel()) {
    if (++fitAttempts <= 8) setTimeout(tryFit, 250);
  } else {
    fitAttempts = 0;
  }
}

async function boot() {
  try {
    if (!window.Live2DCubismCore) throw new Error("Live2DCubismCore 未加载");
    if (!window.PIXI) throw new Error("PIXI 未加载");
    if (!PIXI.live2d || !PIXI.live2d.Live2DModel) throw new Error("pixi-live2d-display 插件未挂载");

    app = new PIXI.Application({
      width: window.innerWidth, height: window.innerHeight,
      backgroundColor: 0x101014, antialias: true, autoDensity: true,
      resolution: Math.min(window.devicePixelRatio || 1, 2),
      preserveDrawingBuffer: true,
    });
    document.getElementById("stage").appendChild(app.view);

    // CPU 治理（D12 附带项）：idle+口型（12.5Hz 包络）30fps 足够，
    // 原 rAF 全速 60fps 在待命态为主进程 73% CPU 的主因之一；
    // 视图不可见（document.hidden）时停止 ticker，恢复可见再启动
    app.ticker.maxFPS = 30;
    document.addEventListener("visibilitychange", function () {
      if (!app || !app.ticker) return;
      if (document.hidden) {
        if (app.ticker.started) app.ticker.stop();
      } else if (!app.ticker.started) {
        app.ticker.start();
      }
    });

    model = await PIXI.live2d.Live2DModel.from(MODEL_URL, { autoInteract: false });

    wrapper = new PIXI.Container();
    wrapper.addChild(model);
    app.stage.addChild(wrapper);
    wrapper.position.set(app.screen.width / 2, app.screen.height / 2);

    var im = model.internalModel;
    im.on("afterMotionUpdate", applyExternalParams);
    // 窗口尺寸变化后重排（QtWebEngine 视图 layout 晚于页面初始化的场景由此覆盖）
    window.addEventListener("resize", function () {
      app.renderer.resize(window.innerWidth, window.innerHeight);
      fitAttempts = 0;
      tryFit();
    });

    setBadge("ready | state=" + external.state);
    tryFit();                 // 首次标定（失败自动重试，见 tryFit）
    // 首次 layout 稳定后强制重算一次（双 rAF，覆盖视图尺寸晚于初始化）
    requestAnimationFrame(function () {
      requestAnimationFrame(function () { window.__fitModel(); });
    });
    window.__avatarReady = true;
  } catch (e) {
    window.__avatarError = String(e && e.stack || e);
    window.__errors.push("boot: " + window.__avatarError);
    setBadge("ERROR");
  }
}

// ---- 对外 API（QML 经 runJavaScript 驱动；语义与 lab 测试 API 一致） ----
window.__avatarAPI = {
  setMouthOpen: function (v) {
    external.mouthOpen = clamp01(v);
    applyExternalParams();
    return { mouthOpen: external.mouthOpen, param: getParam("ParamMouthOpenY") };
  },
  setExpression: function (e) {
    if (!EXPRESSIONS.hasOwnProperty(e)) return { ok: false, error: "unknown expression: " + e };
    external.expression = e;
    applyExternalParams();
    return { ok: true, expression: e };
  },
  setState: function (s) {
    var valid = ["idle", "listening", "thinking", "speaking", "interrupted"];
    if (valid.indexOf(s) < 0) return { ok: false, error: "unknown state: " + s };
    external.state = s;
    setBadge("state=" + s);
    return { ok: true, state: s };
  },
  setHead: function (x, y, z) {
    external.head = { x: clampNum(x, -30, 30), y: clampNum(y, -30, 30), z: clampNum(z, -30, 30) };
    applyExternalParams();
    return { head: { x: external.head.x, y: external.head.y, z: external.head.z } };
  },
  setEyes: function (open) {
    external.eyeOpen = clamp01(open);
    applyExternalParams();
    return { eyeOpen: external.eyeOpen };
  },
  resetMouth: function () {
    external.mouthOpen = 0;
    applyExternalParams();
    return { mouthOpen: 0, param: getParam("ParamMouthOpenY") };
  },
  modelInfo: function () {
    if (!model) return { ready: false, avatarReady: !!window.__avatarReady,
                         error: window.__avatarError };
    var im = model.internalModel;
    var mm = im.motionManager;
    return {
      ready: true,
      avatarReady: true,
      id: (im.settings && im.settings.name) || "Hiyori",
      width: Math.round(model.width), height: Math.round(model.height),
      state: external.state, expression: external.expression,
      // D12 验证面：motion 挂载 / XHR 失败 / 当前像素 bbox
      // （0.4.0 可观测字段：mm.playing、mm.state.currentGroup、mm.groups.idle）
      motion: {
        group: (mm && mm.state && mm.state.currentGroup) || null,
        playing: !!(mm && mm.playing),
        idleGroup: (mm && mm.groups && mm.groups.idle) || null,
        groups: (im.settings && im.settings.motions)
                ? Object.keys(im.settings.motions) : [],
      },
      xhrFailures: xhrFailures(),
      xhrCount: window.__xhrLog.length,
      bbox: contentBBox(),
      hidden: !!document.hidden,                     // offscreen 诊断用
      tickerRunning: !!(app && app.ticker && app.ticker.started),
      fps: app ? Math.round(app.ticker.FPS) : 0,
      params: {
        mouthOpenY: getParam("ParamMouthOpenY"),
        mouthForm: getParam("ParamMouthForm"),
        eyeLOpen: getParam("ParamEyeLOpen"),
        angleX: getParam("ParamAngleX"),
        angleZ: getParam("ParamAngleZ"),
      },
    };
  },
  refit: function () {          // 视图尺寸变化后由 QML/探针强制重算取景
    fitAttempts = 0;
    return { ok: window.__fitModel(), bbox: contentBBox() };
  },
  destroyInstance: function () {   // 验收 f：资源释放（lab 已验证 WebGL context lost）
    overridesActive = false;
    var canvas = document.querySelector("#stage canvas");
    if (model) {
      model.destroy({ children: true });
      model = null;
    }
    if (app) {
      app.destroy(true, { children: true, texture: true, baseTexture: true });
      app = null;
    }
    var ctxLost = false;
    if (canvas) {
      var gl = canvas.getContext("webgl2") || canvas.getContext("webgl") || canvas.getContext("experimental-webgl");
      if (gl) {
        if (!gl.isContextLost()) {
          var ext = gl.getExtension("WEBGL_lose_context");
          if (ext) ext.loseContext();
        }
        ctxLost = gl.isContextLost();
      }
    }
    window.__avatarReady = false;
    return { destroyed: true, canvasCount: document.querySelectorAll("#stage canvas").length, ctxLost: ctxLost };
  },
};

boot();
