"use strict";
const $ = (id) => document.getElementById(id);
let lastDatasetRefreshMs = 0;

/* ---------- logging + toast ---------- */
const log = (msg) => {
  const el = $("log");
  if (el) el.textContent = `${new Date().toLocaleTimeString()} ${msg}\n` + el.textContent;
};
function toast(msg, cls) {
  const wrap = $("toasts");
  if (!wrap) return;
  const el = document.createElement("div");
  el.className = `toast ${cls || ""}`;
  el.textContent = msg;
  wrap.appendChild(el);
  setTimeout(() => {
    el.classList.add("leaving");
    setTimeout(() => el.remove(), 220);
  }, cls === "bad" ? 6000 : 3200);
}

/* ---------- fetch helpers ---------- */
async function api(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: {"content-type": "application/json"},
    body: JSON.stringify(body || {})
  });
  const data = await res.json();
  if (!res.ok || data.ok === false) throw new Error(data.error || res.statusText);
  return data;
}
async function getJson(path) {
  const res = await fetch(path);
  const data = await res.json();
  if (!res.ok || data.ok === false) throw new Error(data.error || res.statusText);
  return data;
}
async function withLoading(btn, fn) {
  if (btn) btn.classList.add("loading");
  try { return await fn(); }
  finally { if (btn) btn.classList.remove("loading"); }
}

function pill(text, cls) {
  return `<span class="pill ${cls || ""}">${text}</span>`;
}

/* ---------- label maps ---------- */
function stateText(state) {
  const map = {
    idle: "空闲",
    starting: "启动中",
    recording: "采集中",
    saving: "保存中",
    unlabeled: "待标注",
    moving_ready: "归位中",
    resetting_realsense: "重置 RealSense",
    stopped: "已停止",
    error: "错误"
  };
  return map[state] || state;
}
function cameraLabel(name) {
  const map = {
    main: "主视角",
    wrist: "腕部",
    wrist_left: "左腕",
    wrist_right: "右腕",
    left: "左",
    right: "右",
    realsense: "深度相机"
  };
  return map[name] || name;
}
const CAM_ORDER = {main: 0, wrist: 1, wrist_left: 1, wrist_right: 2, left: 3, right: 4, realsense: 5};
function sortedCamNames(cams) {
  return Object.keys(cams || {}).sort(
    (a, b) => (CAM_ORDER[a] ?? 99) - (CAM_ORDER[b] ?? 99) || a.localeCompare(b)
  );
}
function cameraPill(name, cam) {
  const ok = cam && cam.ok;
  return pill(`${cameraLabel(name)} ${ok ? "正常" : "等待"}`, ok ? "good" : "warn");
}

/* ============================================================
   CameraStage — main on top, wrist views below. Every tile is an
   INDEPENDENT pan / zoom viewport with its own visible controls,
   wheel zoom, drag-to-pan and fullscreen. Stream <img> nodes are
   created once and MOVED on layout, so MJPEG never reconnects.
   ============================================================ */
const CameraStage = (() => {
  const nodes = new Map();   // name -> {wrap, view, img, latEl, vt, place}
  let order = [];
  const MIN = 1, MAX = 6;

  function build(name) {
    const wrap = document.createElement("div");
    wrap.className = "cam";
    wrap.dataset.cam = name;
    wrap.tabIndex = 0;
    wrap.innerHTML = `
      <div class="cam-view"><img src="/stream/${encodeURIComponent(name)}" draggable="false"></div>
      <div class="cam-hud"><span class="name">${cameraLabel(name)}</span><span class="lat">-- fps</span></div>
      <div class="cam-controls">
        <button class="c-out" title="缩小">−</button>
        <button class="c-in" title="放大">+</button>
        <span class="sep"></span>
        <button class="c-reset" title="复位">↺</button>
        <button class="c-full" title="全屏">⛶</button>
      </div>
      <div class="cam-overlay"><div class="spin"></div><div>等待信号…</div></div>`;
    const node = {
      wrap,
      view: wrap.querySelector(".cam-view"),
      img: wrap.querySelector("img"),
      latEl: wrap.querySelector(".lat"),
      vt: {scale: 1, tx: 0, ty: 0},
      place: null,
    };

    node.img.addEventListener("load", () => {
      if (node.img.naturalWidth && node.img.naturalHeight) {
        setCameraAspect(node, node.img.naturalWidth, node.img.naturalHeight);
      }
    });

    wrap.querySelector(".c-in").addEventListener("click", (e) => { e.stopPropagation(); if (imageZoomEnabled()) zoomCenter(node, 1.4); });
    wrap.querySelector(".c-out").addEventListener("click", (e) => { e.stopPropagation(); if (imageZoomEnabled()) zoomCenter(node, 1 / 1.4); });
    wrap.querySelector(".c-reset").addEventListener("click", (e) => { e.stopPropagation(); reset(node); });
    wrap.querySelector(".c-full").addEventListener("click", (e) => { e.stopPropagation(); toggleFullscreen(node.wrap); });

    node.view.addEventListener("wheel", (e) => {
      if (!imageZoomEnabled()) return;
      e.preventDefault();
      zoomAt(node, e.clientX, e.clientY, e.deltaY < 0 ? 1.12 : 1 / 1.12);
    }, {passive: false});

    node.view.addEventListener("dblclick", (e) => {
      if (!imageZoomEnabled()) return;
      if (node.vt.scale > 1.001) reset(node);
      else zoomAt(node, e.clientX, e.clientY, 2.2);
    });

    let drag = null;
    node.view.addEventListener("pointerdown", (e) => {
      if (!imageZoomEnabled() || node.vt.scale <= 1.001) return;
      drag = {x: e.clientX, y: e.clientY};
      node.view.classList.add("panning");
      node.view.setPointerCapture(e.pointerId);
    });
    node.view.addEventListener("pointermove", (e) => {
      if (!drag) return;
      node.vt.tx += e.clientX - drag.x;
      node.vt.ty += e.clientY - drag.y;
      drag = {x: e.clientX, y: e.clientY};
      clampPan(node);
      apply(node);
    });
    const endDrag = () => { drag = null; node.view.classList.remove("panning"); };
    node.view.addEventListener("pointerup", endDrag);
    node.view.addEventListener("pointercancel", endDrag);

    return node;
  }

  function imageZoomEnabled() {
    const stage = $("cameraGrid");
    return Boolean(document.fullscreenElement) || stage?.dataset.layoutMode === "inspect";
  }

  function apply(node) {
    const {scale, tx, ty} = node.vt;
    node.img.style.transform = `translate(${tx}px, ${ty}px) scale(${scale})`;
    node.wrap.classList.toggle("zoomed", scale > 1.001);
  }
  function reset(node) { node.vt = {scale: 1, tx: 0, ty: 0}; apply(node); }
  function clampPan(node) {
    const r = node.view.getBoundingClientRect();
    const minX = r.width * (1 - node.vt.scale), minY = r.height * (1 - node.vt.scale);
    node.vt.tx = Math.min(0, Math.max(minX, node.vt.tx));
    node.vt.ty = Math.min(0, Math.max(minY, node.vt.ty));
  }
  function zoomAt(node, clientX, clientY, factor) {
    const r = node.view.getBoundingClientRect();
    const px = clientX - r.left, py = clientY - r.top;
    const next = Math.min(MAX, Math.max(MIN, node.vt.scale * factor));
    if (next === node.vt.scale) return;
    node.vt.tx = px - (px - node.vt.tx) * (next / node.vt.scale);
    node.vt.ty = py - (py - node.vt.ty) * (next / node.vt.scale);
    node.vt.scale = next;
    if (node.vt.scale <= 1.001) { node.vt.tx = 0; node.vt.ty = 0; }
    clampPan(node);
    apply(node);
  }
  function zoomCenter(node, factor) {
    const r = node.view.getBoundingClientRect();
    zoomAt(node, r.left + r.width / 2, r.top + r.height / 2, factor);
  }
  function toggleFullscreen(wrap) {
    if (document.fullscreenElement) document.exitFullscreen();
    else if (wrap.requestFullscreen) wrap.requestFullscreen();
  }

  function setCameraAspect(node, width, height) {
    const w = Number(width || 0);
    const h = Number(height || 0);
    if (!node || !w || !h) return;
    node.wrap.style.setProperty("--camera-aspect", `${w} / ${h}`);
  }

  function sync(cams) {
    const names = sortedCamNames(cams);
    for (const name of names) if (!nodes.has(name)) nodes.set(name, build(name));
    for (const name of [...nodes.keys()]) {
      if (!names.includes(name)) { nodes.get(name).wrap.remove(); nodes.delete(name); }
    }
    order = names;
  }

  function layout() {
    const main = $("stageMain"), left = $("stageThumbLeft"), right = $("stageThumbRight");
    if (!main || !left || !right) return;
    const primary = order.includes("main") ? "main" : order[0];
    let wristIndex = 0;
    for (const name of order) {
      const node = nodes.get(name);
      if (!node) continue;
      const place = name === primary ? "main" : "thumb";
      let parent = main;
      if (place === "thumb") {
        parent = wristIndex === 0 ? left : right;
        wristIndex += 1;
      }
      if (node.place !== place) {
        node.place = place;
        node.wrap.classList.toggle("in-main", place === "main");
        node.wrap.classList.toggle("in-thumb", place === "thumb");
        reset(node);              // view box changes size between slots
        parent.appendChild(node.wrap);
      } else if (node.wrap.parentElement !== parent) {
        parent.appendChild(node.wrap);
      }
    }
  }

  function update(cams) {
    sync(cams);
    layout();
    for (const name of order) {
      const node = nodes.get(name);
      const cam = cams[name] || {};
      const fps = cam.fps ? Number(cam.fps).toFixed(1) : "--";
      const age = cam.last_frame_age_ms;
      setCameraAspect(node, cam.width || node.img.naturalWidth, cam.height || node.img.naturalHeight);
      let latCls = "", ageTxt = "--";
      if (age != null) { ageTxt = `${age} ms`; latCls = age > 120 ? "bad" : (age > 60 ? "warn" : ""); }
      node.latEl.className = `lat ${cam.ok ? latCls : "bad"}`;
      node.latEl.textContent = `${fps} fps · ${ageTxt}`;
      node.wrap.classList.toggle("down", !cam.ok);
    }
  }

  function resetAll() {
    for (const node of nodes.values()) reset(node);
  }

  return {update, resetAll};
})();

const cameraLayoutMode = {
  current: "fit",
  presets: {
    fit: {scale: 88, mainShare: 58, wristShare: 28, split: 50},
    collect: {scale: 94, mainShare: 64, wristShare: 28, split: 50},
    inspect: {scale: 100, mainShare: 70, wristShare: 34, split: 50},
  }
};

function clampNumber(value, min, max, fallback) {
  const n = Number(value);
  if (!Number.isFinite(n)) return fallback;
  return Math.min(max, Math.max(min, n));
}

function applyCameraLayout() {
  const stage = $("cameraGrid");
  const scale = $("cameraLayoutScale");
  const main = $("cameraMainShare");
  const wrist = $("cameraWristShare");
  const split = $("cameraWristSplit");
  if (!stage || !scale || !main || !wrist || !split) return;

  const scalePct = clampNumber(scale.value, Number(scale.min), Number(scale.max), 88);
  const mainShare = clampNumber(main.value, Number(main.min), Number(main.max), 58);
  const wristShare = clampNumber(wrist.value, Number(wrist.min), Number(wrist.max), 28);
  const left = clampNumber(split.value, Number(split.min), Number(split.max), 50);

  stage.dataset.layoutMode = cameraLayoutMode.current;
  if (cameraLayoutMode.current !== "inspect") CameraStage.resetAll();
  stage.style.setProperty("--camera-layout-scale", String(scalePct / 100));
  stage.style.setProperty("--camera-main-share", String(mainShare));
  stage.style.setProperty("--camera-wrist-share", String(wristShare));
  stage.style.setProperty("--wrist-left", `${left}%`);
  stage.style.setProperty("--wrist-right", `${100 - left}%`);

  document.querySelectorAll("[data-layout-mode]").forEach((button) => {
    button.classList.toggle("active", button.dataset.layoutMode === cameraLayoutMode.current);
  });
}

function setCameraLayoutPreset(mode) {
  const preset = cameraLayoutMode.presets[mode] || cameraLayoutMode.presets.fit;
  cameraLayoutMode.current = mode in cameraLayoutMode.presets ? mode : "fit";
  const scale = $("cameraLayoutScale");
  const main = $("cameraMainShare");
  const wrist = $("cameraWristShare");
  const split = $("cameraWristSplit");
  if (scale) scale.value = String(preset.scale);
  if (main) main.value = String(preset.mainShare);
  if (wrist) wrist.value = String(preset.wristShare);
  if (split) split.value = String(preset.split);
  applyCameraLayout();
}

function bindSplitter(splitter, axis, onDelta) {
  const stage = $("cameraGrid");
  if (!splitter || !stage) return;
  let drag = null;
  splitter.addEventListener("pointerdown", (event) => {
    drag = {x: event.clientX, y: event.clientY};
    splitter.classList.add("dragging");
    stage.classList.add("resizing");
    splitter.setPointerCapture(event.pointerId);
  });
  splitter.addEventListener("pointermove", (event) => {
    if (!drag) return;
    const delta = axis === "x" ? event.clientX - drag.x : event.clientY - drag.y;
    drag = {x: event.clientX, y: event.clientY};
    onDelta(delta);
  });
  const end = () => {
    drag = null;
    splitter.classList.remove("dragging");
    stage.classList.remove("resizing");
  };
  splitter.addEventListener("pointerup", end);
  splitter.addEventListener("pointercancel", end);
}

function initCameraSizing() {
  const scale = $("cameraLayoutScale");
  const main = $("cameraMainShare");
  const wrist = $("cameraWristShare");
  const split = $("cameraWristSplit");
  const rowBar = $("cameraRowSplitter");
  const colBar = $("cameraColSplitter");
  if (!scale || !main || !wrist || !split || !rowBar || !colBar) return;

  document.querySelectorAll("[data-layout-mode]").forEach((button) => {
    button.addEventListener("click", () => setCameraLayoutPreset(button.dataset.layoutMode));
  });
  [scale, main, wrist, split].forEach((input) => input.addEventListener("input", () => {
    cameraLayoutMode.current = "custom";
    applyCameraLayout();
  }));

  bindSplitter(rowBar, "y", (deltaPx) => {
    const board = $("cameraBoard");
    const height = board ? board.getBoundingClientRect().height : window.innerHeight;
    const delta = deltaPx / Math.max(1, height) * 100;
    main.value = String(clampNumber(Number(main.value) + delta, Number(main.min), Number(main.max), 58));
    wrist.value = String(clampNumber(Number(wrist.value) - delta * 0.5, Number(wrist.min), Number(wrist.max), 28));
    cameraLayoutMode.current = "custom";
    applyCameraLayout();
  });
  bindSplitter(colBar, "x", (deltaPx) => {
    const board = $("cameraBoard");
    const width = board ? board.getBoundingClientRect().width : window.innerWidth;
    const delta = deltaPx / Math.max(1, width) * 100;
    split.value = String(clampNumber(Number(split.value) + delta, Number(split.min), Number(split.max), 50));
    cameraLayoutMode.current = "custom";
    applyCameraLayout();
  });

  setCameraLayoutPreset("fit");
}

/* ============================================================
   Buttons disable matrix — preserved verbatim from the original.
   ============================================================ */
function updateButtons(status) {
  const state = status.episode.state;
  const readyBlocked = status.ready?.required_for_recording && status.ready?.state !== "verified";
  const syncBlocked = status.sync?.required_for_recording && status.sync?.state !== "valid";
  const frozen = status.control.safety_frozen;
  $("start").disabled = state === "recording" || readyBlocked || syncBlocked || frozen;
  $("stop").disabled = state !== "recording";
  $("stop").textContent = frozen && state !== "recording" ? "已自动停止" : "停止并保存";
  $("stop").title = frozen && state !== "recording" ? "Safety Frozen：采集已自动停止并保存" : "";
  $("success").disabled = state === "recording" || status.episode.last_saved_episode_index == null;
  $("failure").disabled = state === "recording" || status.episode.last_saved_episode_index == null;
  $("discard").disabled = state === "idle" && status.episode.last_saved_episode_index == null;
  $("moveReady").disabled = state === "recording" || state === "moving_ready" || status.control.dry_teleop_enabled || frozen;
  $("syncMaster").disabled = state === "recording" || state === "moving_ready" || frozen;
  $("syncLeft").disabled = state === "recording" || state === "moving_ready" || frozen;
  $("syncRight").disabled = state === "recording" || state === "moving_ready" || frozen;
  $("enableTeleop").disabled = state === "recording" || state === "moving_ready" || status.control.dry_teleop_enabled || frozen;
  $("disableTeleop").disabled = state === "recording" || !status.control.dry_teleop_enabled;
  $("newDataset").disabled = state === "recording" || frozen;
  $("switchDataset").disabled = state === "recording" || frozen;
  $("exportDryRun").disabled = state === "recording" || frozen;
  $("exportStart").disabled = state === "recording" || frozen;
}

/* ============================================================
   Readiness card + episode strip
   ============================================================ */
function readyRow(key, cls, value) {
  return `<div class="ready-row ${cls}"><span class="rdot"></span><span class="rk">${key}</span><span class="rv">${value}</span></div>`;
}
function renderReadiness(status) {
  const ready = status.ready || {};
  const sync = status.sync || {};
  const frozen = status.control.safety_frozen;
  const req = "· 必需";
  const stMap = {verified: "已校验", valid: "有效", invalid: "无效", unknown: "未知", pending: "待定", moving_ready: "归位中"};
  const armMap = {left: "左", right: "右", both: "双"};
  const st = (s) => stMap[s] || s || "未知";

  const readyCls = ready.state === "verified" ? "ok"
    : (ready.required_for_recording ? "warn" : "off");
  const readyVal = `${st(ready.state)}${ready.required_for_recording ? " " + req : ""}`;

  const syncOk = sync.state === "valid";
  const syncCls = syncOk ? "ok" : (sync.required_for_recording ? "warn" : "off");
  const armList = sync.latest_result?.synced_arms || [];
  const arms = armList.length ? " · " + armList.map((a) => armMap[a] || a).join("+") + "臂" : "";
  const syncVal = `${st(sync.state)}${sync.required_for_recording ? " " + req : ""}${arms}`;

  const teleopOn = status.control.dry_teleop_enabled;
  const teleopCls = teleopOn ? "ok" : "off";
  const teleopVal = teleopOn ? "已启用 · 试运行" : "未启用";

  const freezeCls = frozen ? "bad" : "ok";
  const freezeVal = frozen ? `${status.control.freeze_reason || "已冻结"} · ${status.episode.auto_stop_save_status || "--"}` : "正常";

  $("readiness").innerHTML = [
    readyRow("就绪", readyCls, readyVal),
    readyRow("同步", syncCls, syncVal),
    readyRow("遥操作", teleopCls, teleopVal),
    readyRow("冻结", freezeCls, freezeVal),
  ].join("");

  const state = status.episode.state;
  const strip = $("epiStrip");
  strip.className = `epi-strip ${state === "recording" ? "recording" : ""}`;
  const saved = status.episode.last_saved_episode_index ?? "--";
  strip.innerHTML =
    `<span><span class="epi-state">${stateText(state)}</span> · 第 ${status.episode.episode_index} 段</span>` +
    `<span>帧 ${status.episode.frame_count} · 已存 ${saved}</span>`;
}

/* ============================================================
   Dataset / export (low-frequency drawers)
   ============================================================ */
function datasetStateText(state) {
  const map = {
    root_missing: "root 不存在，可创建",
    empty_root: "空目录，可初始化",
    appendable: "可继续追加",
    legacy_unknown: "legacy/未知，禁止追加",
    semantic_mismatch: "语义不一致，需换 root",
    invalid_dataset_root: "无效 root"
  };
  return map[state] || state || "unknown";
}
async function refreshDatasetStatus(force) {
  const now = Date.now();
  if (!force && now - lastDatasetRefreshMs < 5000) return null;
  lastDatasetRefreshMs = now;
  const data = await getJson("/api/dataset/status");
  const cls = data.can_append || data.can_create ? "good" : "warn";
  $("datasetLifecycle").innerHTML = [
    pill(datasetStateText(data.root_state), cls),
    `<div>目录: ${data.root}</div>`,
    `<div>数据集 ID: ${data.repo_id}</div>`,
    `<div>会话目录: ${data.session_root}</div>`,
    data.reason ? `<div>原因: ${data.reason}</div>` : ""
  ].join("");
  const meta = $("accDatasetMeta");
  if (meta) meta.textContent = datasetStateText(data.root_state);
  if (!$("datasetRoot").value) $("datasetRoot").value = data.root || "";
  if (!$("datasetRepoId").value) $("datasetRepoId").value = data.repo_id || "";
  if (!$("datasetSessionRoot").value) $("datasetSessionRoot").value = data.session_root || "";
  if (!$("exportOutputRoot").value && data.root) $("exportOutputRoot").value = `${data.root}_training_export`;
  if (!$("exportOutputRepoId").value && data.repo_id) $("exportOutputRepoId").value = `${data.repo_id}_training_export`;
  return data;
}
function exportPayload() {
  return {
    source_root: $("datasetRoot").value,
    source_repo_id: $("datasetRepoId").value,
    output_root: $("exportOutputRoot").value,
    output_repo_id: $("exportOutputRepoId").value,
    config_file: $("exportConfigFile").value || null
  };
}
function renderExportStatus(data) {
  if (!data) return;
  const meta = $("accExportMeta");
  const stMap = {succeeded: "导出成功", failed: "导出失败", running: "导出中", pending: "排队中"};
  if (data.status) {
    const cls = data.status === "succeeded" ? "good" : (data.status === "failed" ? "bad" : "warn");
    const label = stMap[data.status] || `导出 ${data.status}`;
    const result = data.result || {};
    $("exportStatus").innerHTML = [
      pill(label, cls),
      data.job_id ? `<div>任务号: ${data.job_id}</div>` : "",
      result.output_root ? `<div>输出: ${result.output_root}</div>` : "",
      result.exported_episode_count != null ? `<div>已导出: ${result.exported_episode_count} 段</div>` : "",
      data.error ? `<div>错误: ${data.error}</div>` : ""
    ].join("");
    if (meta) meta.textContent = label;
    return;
  }
  const excluded = data.excluded_reasons ? JSON.stringify(data.excluded_reasons) : "{}";
  $("exportStatus").innerHTML = [
    pill("试运行", "warn"),
    `<div>可导出: ${data.exported_episode_count ?? 0} 段</div>`,
    `<div>排除: ${data.excluded_episode_count ?? 0} 段</div>`,
    `<div>原因: ${excluded}</div>`
  ].join("");
  if (meta) meta.textContent = `试运行 · ${data.exported_episode_count ?? 0} 段`;
}
async function refreshExportStatus() {
  try { renderExportStatus(await getJson("/api/export/training-package/status")); }
  catch (err) { log(`导出状态刷新失败：${err.message}`); }
}

/* ============================================================
   Main poll
   ============================================================ */
async function refresh() {
  try {
    const status = await getJson("/api/status");
    if (!$("task").value) $("task").value = status.control.default_task || "";
    const cams = status.cameras || {};
    CameraStage.update(cams);

    const frozenBanner = status.control.safety_frozen
      ? [
          pill("Safety Frozen", "bad"),
          pill("采集已自动停止并保存；该 episode 已污染，不能 accepted/export；需重启/重连后继续", "warn"),
          pill("Label 可保存，但 accepted=false", "warn")
        ]
      : [];
    $("safetyBanner").innerHTML = frozenBanner.join("");

    const recording = status.episode.state === "recording";
    $("topStatus").innerHTML = [
      pill(stateText(status.episode.state), recording ? "rec" : ""),
      pill(`第 ${status.episode.episode_index} 段`),
      pill(status.robot.connected ? "机器人 正常" : "机器人 等待", status.robot.connected ? "good" : "warn"),
      pill(status.teleop.connected ? "遥操作 正常" : "遥操作 等待", status.teleop.connected ? "good" : "warn"),
      ...sortedCamNames(cams).map((name) => cameraPill(name, cams[name]))
    ].join("");

    renderReadiness(status);

    $("details").innerHTML = [
      ["数据集", status.dataset.root],
      ["会话", status.session_id],
      ["帧数", status.episode.frame_count],
      ["已保存", status.episode.last_saved_episode_index ?? "--"],
      ["保存耗时", status.episode.save_duration_s == null ? "--" : `${status.episode.save_duration_s}s`],
      ["就绪", `${status.ready?.state || "unknown"}${status.ready?.required_for_recording ? " / required" : ""}`],
      ["同步", `${status.sync?.state || "unknown"}${status.sync?.required_for_recording ? " / required" : ""}${status.sync?.latest_result?.synced_arms ? " / " + status.sync.latest_result.synced_arms.join("+") : ""}`],
      ["遥操作", status.control.dry_teleop_enabled ? "enabled" : "disabled"],
      ["冻结", status.control.safety_frozen ? `${status.control.freeze_reason || "frozen"} / ${status.episode.auto_stop_save_status || "--"}` : "no"],
      ["状态消息", status.message || ""]
    ].map(([k, v]) => `<div>${k}</div><div>${v}</div>`).join("");

    updateButtons(status);
    refreshDatasetStatus(false).catch((err) => log(`数据集状态刷新失败：${err.message}`));
  } catch (err) {
    log(`状态刷新失败：${err.message}`);
  }
}

/* ============================================================
   Action handlers
   ============================================================ */
$("start").onclick = async () => {
  try { const data = await withLoading($("start"), () => api("/api/episode/start", {task: $("task").value})); log(`已开始 episode ${data.episode_index}`); toast(`开始采集 · episode ${data.episode_index}`, "good"); refresh(); }
  catch (err) { log(`开始失败：${err.message}`); toast(`开始失败：${err.message}`, "bad"); }
};
$("stop").onclick = async () => {
  try { const data = await withLoading($("stop"), () => api("/api/episode/stop", {})); log(`已停止并保存 episode ${data.episode_index}`); toast(`已停止并保存 · episode ${data.episode_index}`, "good"); refresh(); }
  catch (err) { log(`停止失败：${err.message}`); toast(`停止失败：${err.message}`, "bad"); }
};
$("success").onclick = async () => {
  try { const data = await withLoading($("success"), () => api("/api/episode/label", {label: "success"})); const gate = data.record.accepted ? "accepted" : `accepted=false：${(data.record.acceptance_reasons || []).join(", ")}`; log(`episode ${data.episode_index} 标记为 success；${gate}`); toast(`success · ${gate}`, data.record.accepted ? "good" : "warn"); refresh(); }
  catch (err) { log(`标注失败：${err.message}`); toast(`标注失败：${err.message}`, "bad"); }
};
$("failure").onclick = async () => {
  try { const data = await withLoading($("failure"), () => api("/api/episode/label", {label: "failure"})); log(`episode ${data.episode_index} 标记为 failure`); toast(`episode ${data.episode_index} 标记为 failure`, "warn"); refresh(); }
  catch (err) { log(`标注失败：${err.message}`); toast(`标注失败：${err.message}`, "bad"); }
};
$("discard").onclick = async () => {
  if (!confirm("确认丢弃当前 episode？该操作不可恢复。")) return;
  try { const data = await withLoading($("discard"), () => api("/api/episode/discard", {})); log(`已丢弃 ${data.episode_index ?? "current"}`); toast(`已丢弃 ${data.episode_index ?? "current"}`, "warn"); refresh(); }
  catch (err) { log(`丢弃失败：${err.message}`); toast(`丢弃失败：${err.message}`, "bad"); }
};
$("moveReady").onclick = async () => {
  try { const data = await withLoading($("moveReady"), () => api("/api/ready/move", {})); const ready = data.ready || {}; log(`Move to Ready：${ready.ok ? "verified" : "failed"}，max_error=${ready.max_abs_error ?? "--"}`); toast(`Move to Ready：${ready.ok ? "verified" : "failed"}`, ready.ok ? "good" : "bad"); refresh(); }
  catch (err) { log(`Move to Ready 失败：${err.message}`); toast(`Move to Ready 失败：${err.message}`, "bad"); }
};
$("syncMaster").onclick = async () => {
  try { const data = await withLoading($("syncMaster"), () => api("/api/sync/master", {arm: "both"})); const sync = data.sync || {}; log(`Sync Master：${sync.state || "unknown"}，arms=${(sync.synced_arms || []).join("+") || "--"}，keys=${(sync.keys || []).length}`); toast(`Sync Master：${sync.state || "unknown"}`, sync.state === "valid" ? "good" : "warn"); refresh(); }
  catch (err) { log(`Sync Master 失败：${err.message}`); toast(`Sync Master 失败：${err.message}`, "bad"); }
};
$("syncLeft").onclick = async () => {
  try { const data = await withLoading($("syncLeft"), () => api("/api/sync/master", {arm: "left"})); const sync = data.sync || {}; log(`Sync Left：${sync.state || "unknown"}，arms=${(sync.synced_arms || []).join("+") || "--"}，keys=${(sync.keys || []).length}`); toast(`Sync Left：${sync.state || "unknown"}`, sync.state === "valid" ? "good" : "warn"); refresh(); }
  catch (err) { log(`Sync Left 失败：${err.message}`); toast(`Sync Left 失败：${err.message}`, "bad"); }
};
$("syncRight").onclick = async () => {
  try { const data = await withLoading($("syncRight"), () => api("/api/sync/master", {arm: "right"})); const sync = data.sync || {}; log(`Sync Right：${sync.state || "unknown"}，arms=${(sync.synced_arms || []).join("+") || "--"}，keys=${(sync.keys || []).length}`); toast(`Sync Right：${sync.state || "unknown"}`, sync.state === "valid" ? "good" : "warn"); refresh(); }
  catch (err) { log(`Sync Right 失败：${err.message}`); toast(`Sync Right 失败：${err.message}`, "bad"); }
};
$("enableTeleop").onclick = async () => {
  try { await withLoading($("enableTeleop"), () => api("/api/teleop/enable", {})); log("Dry teleop 已启用，可小幅检查方向，不会写入数据"); toast("Dry teleop 已启用", "good"); refresh(); }
  catch (err) { log(`启用 Dry teleop 失败：${err.message}`); toast(`启用 Dry teleop 失败：${err.message}`, "bad"); }
};
$("disableTeleop").onclick = async () => {
  try { await withLoading($("disableTeleop"), () => api("/api/teleop/disable", {})); log("Dry teleop 已关闭"); toast("Dry teleop 已关闭", "good"); refresh(); }
  catch (err) { log(`关闭 Dry teleop 失败：${err.message}`); toast(`关闭 Dry teleop 失败：${err.message}`, "bad"); }
};
$("refreshDataset").onclick = async () => {
  try { await withLoading($("refreshDataset"), () => refreshDatasetStatus(true)); log("数据集状态已刷新"); }
  catch (err) { log(`数据集状态刷新失败：${err.message}`); toast(`数据集状态刷新失败：${err.message}`, "bad"); }
};
$("newDataset").onclick = async () => {
  try { const data = await withLoading($("newDataset"), () => api("/api/dataset/new", {name: $("datasetName").value})); log(`已创建/切换新测试数据集：${data.dataset.root}`); toast("已创建新测试数据集", "good"); $("datasetRoot").value = data.dataset.root; $("datasetRepoId").value = data.dataset.repo_id; $("datasetSessionRoot").value = data.dataset.session_root; refresh(); }
  catch (err) { log(`创建新数据集失败：${err.message}`); toast(`创建新数据集失败：${err.message}`, "bad"); }
};
$("switchDataset").onclick = async () => {
  try { const data = await withLoading($("switchDataset"), () => api("/api/dataset/switch", {root: $("datasetRoot").value, repo_id: $("datasetRepoId").value, session_root: $("datasetSessionRoot").value})); log(`已切换数据集：${data.dataset.root}`); toast("已切换 dataset root", "good"); refresh(); }
  catch (err) { log(`切换数据集失败：${err.message}`); toast(`切换数据集失败：${err.message}`, "bad"); }
};
$("exportDryRun").onclick = async () => {
  try { const data = await withLoading($("exportDryRun"), () => api("/api/export/training-package/dry-run", exportPayload())); renderExportStatus(data); log(`导出 dry-run：可导出 ${data.exported_episode_count || 0} 条，排除 ${data.excluded_episode_count || 0} 条`); toast(`dry-run：可导出 ${data.exported_episode_count || 0} 条`, "warn"); }
  catch (err) { log(`导出 dry-run 失败：${err.message}`); toast(`导出 dry-run 失败：${err.message}`, "bad"); }
};
$("exportStart").onclick = async () => {
  try { const data = await withLoading($("exportStart"), () => api("/api/export/training-package/start", exportPayload())); renderExportStatus(data); log(`训练包导出已启动：${data.job_id}`); toast(`训练包导出已启动：${data.job_id}`, "good"); }
  catch (err) { log(`训练包导出启动失败：${err.message}`); toast(`训练包导出启动失败：${err.message}`, "bad"); }
};

/* ---------- accordions ---------- */
document.querySelectorAll(".acc-head").forEach((head) => {
  head.addEventListener("click", () => head.parentElement.classList.toggle("open"));
});

initCameraSizing();
refresh();
setInterval(refresh, 1000);
setInterval(refreshExportStatus, 3000);
