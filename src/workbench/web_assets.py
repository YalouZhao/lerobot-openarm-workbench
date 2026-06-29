from __future__ import annotations

from pathlib import Path

_STATIC_DIR = Path(__file__).resolve().parent / "static"


def _read_static(name: str) -> str:
    return (_STATIC_DIR / name).read_text(encoding="utf-8")


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>LeRobot 采集工作台</title>
  <link rel="stylesheet" href="/static/app.css">
</head>
<body>
  <header>
    <div class="brand"><span class="dot"></span><h1>LeRobot 采集工作台</h1></div>
    <div class="status-row" id="topStatus"></div>
  </header>

  <div id="safetyBanner"></div>

  <main>
    <section class="camera-stage" id="cameraGrid">
      <div class="camera-toolbar">
        <div>
          <div class="camera-title">相机监控</div>
          <div class="camera-subtitle">每个窗口独立占位，允许留白；滑块调窗口尺寸，滚轮只缩放画面内容，拖拽平移。</div>
        </div>
        <div class="camera-size-controls" aria-label="相机窗口尺寸">
          <label for="cameraMainSize">主窗口高度</label>
          <input id="cameraMainSize" type="range" min="42" max="74" value="60">
          <label for="cameraThumbSize">腕部行高</label>
          <input id="cameraThumbSize" type="range" min="16" max="36" value="26">
          <label for="cameraWristSplit">左右腕宽度</label>
          <input id="cameraWristSplit" type="range" min="25" max="75" value="50">
        </div>
      </div>
      <div class="camera-board" id="cameraBoard">
        <div class="stage-main" id="stageMain"></div>
        <div class="camera-splitter row" id="cameraRowSplitter" role="separator" aria-orientation="horizontal" title="拖动调整主视角和腕部视角高度"></div>
        <div class="stage-thumbs" id="stageThumbs">
          <div class="thumb-slot left" id="stageThumbLeft"></div>
          <div class="camera-splitter col" id="cameraColSplitter" role="separator" aria-orientation="vertical" title="拖动调整左右腕部视角宽度"></div>
          <div class="thumb-slot right" id="stageThumbRight"></div>
        </div>
      </div>
    </section>

    <aside class="sidebar">
      <!-- 任务 -->
      <section class="card card-pad">
        <div class="card-title">任务描述</div>
        <textarea id="task" placeholder="用英文填写任务描述…"></textarea>
      </section>

      <!-- 就绪状态 -->
      <section class="card card-pad">
        <div class="card-title">就绪状态</div>
        <div class="readiness" id="readiness"></div>
        <div class="epi-strip" id="epiStrip"></div>
      </section>

      <!-- 核心控制 -->
      <section class="card card-pad">
        <div class="card-title">核心控制</div>
        <div class="stack">
          <button id="moveReady">移动到就绪位</button>
          <div class="sub-label">同步</div>
          <div class="btn-grid three">
            <button id="syncMaster">双臂</button>
            <button id="syncLeft">左臂</button>
            <button id="syncRight">右臂</button>
          </div>
          <div class="btn-row">
            <button id="enableTeleop">启用遥操作</button>
            <button id="disableTeleop" class="ghost">关闭遥操作</button>
          </div>
        </div>
      </section>

      <!-- 采集 + 标注 -->
      <section class="card card-pad">
        <div class="card-title">采集</div>
        <div class="btn-row">
          <button id="start" class="primary lg">开始采集</button>
          <button id="stop" class="lg">停止并保存</button>
        </div>
        <div class="sub-label" style="margin-top:14px">标注</div>
        <div class="btn-grid three">
          <button id="success">标记成功</button>
          <button id="failure">标记失败</button>
          <button id="discard" class="danger">丢弃本段</button>
        </div>
      </section>

      <!-- 数据集（低频） -->
      <section class="acc" id="accDataset">
        <div class="acc-head" data-acc="accDataset">
          <span class="chev">▶</span><span class="acc-name">数据集</span>
          <span class="acc-meta" id="accDatasetMeta"></span>
        </div>
        <div class="acc-body">
          <div class="status-block" id="datasetLifecycle">读取中…</div>
          <label for="datasetName">新测试数据集名称</label>
          <input id="datasetName" placeholder="例如 smoke_0624">
          <div class="btn-grid" style="margin-top:12px">
            <button id="newDataset">创建新数据集</button>
            <button id="refreshDataset" class="ghost">刷新状态</button>
          </div>
          <label for="datasetRoot">数据集目录</label>
          <input id="datasetRoot" placeholder="/tmp/lerobot-.../dataset">
          <label for="datasetRepoId">数据集 ID（repo_id）</label>
          <input id="datasetRepoId" placeholder="local/my_dataset">
          <label for="datasetSessionRoot">会话目录（可选）</label>
          <input id="datasetSessionRoot" placeholder="/tmp/lerobot-.../sessions">
          <div class="btn-row" style="margin-top:12px">
            <button id="switchDataset">切换数据集目录</button>
          </div>
        </div>
      </section>

      <!-- 训练包导出（低频） -->
      <section class="acc" id="accExport">
        <div class="acc-head" data-acc="accExport">
          <span class="chev">▶</span><span class="acc-name">训练包导出</span>
          <span class="acc-meta" id="accExportMeta"></span>
        </div>
        <div class="acc-body">
          <div class="status-block" id="exportStatus">尚未导出</div>
          <label for="exportOutputRoot">输出目录</label>
          <input id="exportOutputRoot" placeholder="/tmp/lerobot-exported-training-dataset">
          <label for="exportOutputRepoId">输出数据集 ID</label>
          <input id="exportOutputRepoId" placeholder="local/exported_training_dataset">
          <label for="exportConfigFile">配置文件（可选）</label>
          <input id="exportConfigFile" placeholder="config/workbench_config.phase1-hardware-test.json">
          <div class="btn-grid" style="margin-top:12px">
            <button id="exportDryRun" class="ghost">试运行导出</button>
            <button id="exportStart">开始导出训练包</button>
          </div>
        </div>
      </section>

      <!-- 运行明细（低频） -->
      <section class="acc" id="accLog">
        <div class="acc-head" data-acc="accLog">
          <span class="chev">▶</span><span class="acc-name">运行明细</span>
          <span class="acc-meta" id="accLogMeta"></span>
        </div>
        <div class="acc-body">
          <div class="kv" id="details"></div>
          <div class="log" id="log"></div>
        </div>
      </section>
    </aside>
  </main>

  <div class="toast-wrap" id="toasts"></div>

  <script src="/static/app.js"></script>
</body>
</html>
"""

APP_CSS = _read_static("app.css")
APP_JS = _read_static("app.js")
