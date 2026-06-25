from __future__ import annotations


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>LeRobot 采集工作台</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f5f7f8;
      --panel: #ffffff;
      --text: #162023;
      --muted: #637174;
      --line: #dce3e5;
      --good: #16875d;
      --bad: #b33b3b;
      --warn: #a66a00;
      --accent: #2457d6;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 12px 16px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
      position: sticky;
      top: 0;
      z-index: 5;
    }
    h1 { font-size: 18px; margin: 0; letter-spacing: 0; }
    .status-row {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
      justify-content: flex-end;
    }
    .pill {
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 4px 9px;
      background: #fbfcfc;
      white-space: nowrap;
    }
    .pill.good { color: var(--good); border-color: #a7d8c4; }
    .pill.bad { color: var(--bad); border-color: #e5b2b2; }
    .pill.warn { color: var(--warn); border-color: #e5cc99; }
    main {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 340px;
      gap: 14px;
      padding: 14px;
      min-height: calc(100vh - 58px);
    }
    .video-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
      align-content: start;
    }
    .camera {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
      min-width: 0;
    }
    .camera .title {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 8px 10px;
      border-bottom: 1px solid var(--line);
      color: var(--muted);
    }
    .camera img {
      width: 100%;
      aspect-ratio: 4 / 3;
      object-fit: contain;
      display: block;
      background: #101517;
    }
    aside {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      align-self: start;
    }
    label {
      display: block;
      color: var(--muted);
      margin-bottom: 6px;
    }
    textarea, input {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px;
      font: inherit;
      color: var(--text);
      resize: vertical;
      min-height: 76px;
      background: #fbfcfc;
    }
    input { min-height: 0; }
    .buttons {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
      margin-top: 10px;
    }
    button {
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #f9fbfb;
      color: var(--text);
      min-height: 36px;
      font: inherit;
      cursor: pointer;
    }
    button.primary { background: var(--accent); color: white; border-color: var(--accent); }
    button.danger { color: var(--bad); }
    button:disabled { opacity: .45; cursor: not-allowed; }
    .kv {
      display: grid;
      grid-template-columns: 128px minmax(0, 1fr);
      gap: 6px 10px;
      margin: 12px 0;
    }
    .kv div:nth-child(odd) { color: var(--muted); }
    .dataset-panel {
      border-top: 1px solid var(--line);
      border-bottom: 1px solid var(--line);
      padding: 10px 0;
      margin: 12px 0;
    }
    .dataset-panel h2 {
      font-size: 14px;
      margin: 0 0 8px;
    }
    .dataset-panel label { margin-top: 8px; }
    .dataset-status {
      color: var(--muted);
      font-size: 12px;
      overflow-wrap: anywhere;
    }
    .log {
      height: 190px;
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px;
      background: #fbfcfc;
      white-space: pre-wrap;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 12px;
    }
    @media (max-width: 1120px) {
      main { grid-template-columns: 1fr; }
      .video-grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <header>
    <h1>LeRobot 采集工作台</h1>
    <div class="status-row" id="topStatus"></div>
  </header>
  <main>
    <section class="video-grid" id="cameraGrid"></section>
    <aside>
      <label for="task">任务描述（英文）</label>
      <textarea id="task"></textarea>
      <div class="buttons">
        <button id="start" class="primary">开始采集</button>
        <button id="stop">停止并保存</button>
        <button id="success">标记 success</button>
        <button id="failure">标记 failure</button>
        <button id="discard" class="danger">丢弃 episode</button>
        <button id="resetRs">重置 RealSense</button>
        <button id="moveReady">Move to Ready</button>
      </div>
      <section class="dataset-panel">
        <h2>数据集</h2>
        <div class="dataset-status" id="datasetLifecycle">读取中…</div>
        <label for="datasetName">新测试数据集名称</label>
        <input id="datasetName" placeholder="例如 smoke_0624">
        <div class="buttons">
          <button id="newDataset">创建新测试数据集</button>
          <button id="refreshDataset">刷新数据集状态</button>
        </div>
        <label for="datasetRoot">切换 root</label>
        <input id="datasetRoot" placeholder="/tmp/lerobot-.../dataset">
        <label for="datasetRepoId">repo_id</label>
        <input id="datasetRepoId" placeholder="local/my_dataset">
        <label for="datasetSessionRoot">session_root（可选）</label>
        <input id="datasetSessionRoot" placeholder="/tmp/lerobot-.../sessions">
        <div class="buttons">
          <button id="switchDataset">切换 dataset root</button>
        </div>
      </section>
      <div class="kv" id="details"></div>
      <div class="log" id="log"></div>
    </aside>
  </main>
  <script>
    const $ = (id) => document.getElementById(id);
    let renderedCameraKey = "";
    let lastDatasetRefreshMs = 0;
    const log = (msg) => {
      const el = $("log");
      el.textContent = `${new Date().toLocaleTimeString()} ${msg}\\n` + el.textContent;
    };
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
    function pill(text, cls) {
      return `<span class="pill ${cls || ""}">${text}</span>`;
    }
    function stateText(state) {
      const map = {
        idle: "空闲",
        starting: "启动中",
        recording: "采集中",
        saving: "保存中",
        unlabeled: "待标注",
        resetting_realsense: "重置 RealSense",
        stopped: "已停止",
        error: "错误"
      };
      return map[state] || state;
    }
    function cameraLabel(name) {
      const map = {
        main: "main 主视角",
        wrist: "wrist 腕部视角",
        left: "left",
        right: "right",
        realsense: "realsense"
      };
      return map[name] || name;
    }
    function cameraPill(name, cam) {
      const ok = cam && cam.ok;
      return pill(`${name} ${ok ? "正常" : "等待"}`, ok ? "good" : "warn");
    }
    function renderCameras(cams) {
      const grid = $("cameraGrid");
      const names = Object.keys(cams || {}).sort((a, b) => {
        const order = {main: 0, wrist: 1, left: 2, right: 3, realsense: 4};
        return (order[a] ?? 99) - (order[b] ?? 99) || a.localeCompare(b);
      });
      const key = names.join(",");
      if (key === renderedCameraKey) {
        for (const name of names) {
          const cam = cams[name] || {};
          const fps = cam.fps ? Number(cam.fps).toFixed(1) : "--";
          const age = cam.last_frame_age_ms != null ? `${cam.last_frame_age_ms}ms` : "--";
          const meta = document.querySelector(`[data-camera-meta="${name}"]`);
          if (meta) meta.textContent = `${fps} fps / ${age}`;
        }
        return;
      }
      renderedCameraKey = key;
      grid.innerHTML = names.map((name) => {
        const cam = cams[name] || {};
        const fps = cam.fps ? Number(cam.fps).toFixed(1) : "--";
        const age = cam.last_frame_age_ms != null ? `${cam.last_frame_age_ms}ms` : "--";
        return `<div class="camera">
          <div class="title"><b>${cameraLabel(name)}</b><span data-camera-meta="${name}">${fps} fps / ${age}</span></div>
          <img src="/stream/${encodeURIComponent(name)}">
        </div>`;
      }).join("");
    }
    function updateButtons(status) {
      const state = status.episode.state;
      $("start").disabled = state === "recording";
      $("stop").disabled = state !== "recording";
      $("success").disabled = state === "recording" || status.episode.last_saved_episode_index == null;
      $("failure").disabled = state === "recording" || status.episode.last_saved_episode_index == null;
      $("discard").disabled = state === "idle" && status.episode.last_saved_episode_index == null;
      $("resetRs").disabled = state === "recording" || !status.control.has_realsense;
      $("moveReady").disabled = state === "recording" || state === "moving_ready";
      $("newDataset").disabled = state === "recording";
      $("switchDataset").disabled = state === "recording";
    }
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
        `<div>root: ${data.root}</div>`,
        `<div>repo_id: ${data.repo_id}</div>`,
        `<div>session_root: ${data.session_root}</div>`,
        data.reason ? `<div>原因: ${data.reason}</div>` : ""
      ].join("");
      if (!$("datasetRoot").value) $("datasetRoot").value = data.root || "";
      if (!$("datasetRepoId").value) $("datasetRepoId").value = data.repo_id || "";
      if (!$("datasetSessionRoot").value) $("datasetSessionRoot").value = data.session_root || "";
      return data;
    }
    async function refresh() {
      try {
        const status = await getJson("/api/status");
        if (!$("task").value) $("task").value = status.control.default_task || "";
        const cams = status.cameras || {};
        renderCameras(cams);
        $("topStatus").innerHTML = [
          pill(stateText(status.episode.state), status.episode.state === "recording" ? "good" : ""),
          pill(`episode ${status.episode.episode_index}`),
          pill(status.robot.connected ? "robot 正常" : "robot 等待", status.robot.connected ? "good" : "warn"),
          pill(status.teleop.connected ? "teleop 正常" : "teleop 等待", status.teleop.connected ? "good" : "warn"),
          ...Object.keys(cams).sort().map((name) => cameraPill(name, cams[name]))
        ].join("");
        $("details").innerHTML = [
          ["数据集", status.dataset.root],
          ["会话", status.session_id],
          ["帧数", status.episode.frame_count],
          ["已保存", status.episode.last_saved_episode_index ?? "--"],
          ["保存耗时", status.episode.save_duration_s == null ? "--" : `${status.episode.save_duration_s}s`],
          ["Ready", `${status.ready?.state || "unknown"}${status.ready?.required_for_recording ? " / required" : ""}`],
          ["状态消息", status.message || ""]
        ].map(([k, v]) => `<div>${k}</div><div>${v}</div>`).join("");
        updateButtons(status);
        refreshDatasetStatus(false).catch((err) => log(`数据集状态刷新失败：${err.message}`));
      } catch (err) {
        log(`状态刷新失败：${err.message}`);
      }
    }
    $("start").onclick = async () => {
      try { const data = await api("/api/episode/start", {task: $("task").value}); log(`已开始 episode ${data.episode_index}`); refresh(); }
      catch (err) { log(`开始失败：${err.message}`); }
    };
    $("stop").onclick = async () => {
      try { const data = await api("/api/episode/stop", {}); log(`已停止并保存 episode ${data.episode_index}`); refresh(); }
      catch (err) { log(`停止失败：${err.message}`); }
    };
    $("success").onclick = async () => {
      try { const data = await api("/api/episode/label", {label: "success"}); const gate = data.record.accepted ? "accepted" : `accepted=false：${(data.record.acceptance_reasons || []).join(", ")}`; log(`episode ${data.episode_index} 标记为 success；${gate}`); refresh(); }
      catch (err) { log(`标注失败：${err.message}`); }
    };
    $("failure").onclick = async () => {
      try { const data = await api("/api/episode/label", {label: "failure"}); log(`episode ${data.episode_index} 标记为 failure`); refresh(); }
      catch (err) { log(`标注失败：${err.message}`); }
    };
    $("discard").onclick = async () => {
      try { const data = await api("/api/episode/discard", {}); log(`已丢弃 ${data.episode_index ?? "current"}`); refresh(); }
      catch (err) { log(`丢弃失败：${err.message}`); }
    };
    $("resetRs").onclick = async () => {
      try { const data = await api("/api/realsense/reset", {}); log(`RealSense 重置结果：${data.ok}`); refresh(); }
      catch (err) { log(`重置失败：${err.message}`); }
    };
    $("moveReady").onclick = async () => {
      try { const data = await api("/api/ready/move", {}); const ready = data.ready || {}; log(`Move to Ready：${ready.ok ? "verified" : "failed"}，max_error=${ready.max_abs_error ?? "--"}`); refresh(); }
      catch (err) { log(`Move to Ready 失败：${err.message}`); }
    };
    $("refreshDataset").onclick = async () => {
      try { await refreshDatasetStatus(true); log("数据集状态已刷新"); }
      catch (err) { log(`数据集状态刷新失败：${err.message}`); }
    };
    $("newDataset").onclick = async () => {
      try { const data = await api("/api/dataset/new", {name: $("datasetName").value}); log(`已创建/切换新测试数据集：${data.dataset.root}`); $("datasetRoot").value = data.dataset.root; $("datasetRepoId").value = data.dataset.repo_id; $("datasetSessionRoot").value = data.dataset.session_root; refresh(); }
      catch (err) { log(`创建新数据集失败：${err.message}`); }
    };
    $("switchDataset").onclick = async () => {
      try { const data = await api("/api/dataset/switch", {root: $("datasetRoot").value, repo_id: $("datasetRepoId").value, session_root: $("datasetSessionRoot").value}); log(`已切换数据集：${data.dataset.root}`); refresh(); }
      catch (err) { log(`切换数据集失败：${err.message}`); }
    };
    refresh();
    setInterval(refresh, 1000);
  </script>
</body>
</html>
"""
