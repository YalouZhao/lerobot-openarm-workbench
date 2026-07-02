# LeRobot OpenArm Workbench

OpenArm 双臂 LeRobot 采集工作台，用于在 4090 采集机上完成真机遥操作、数据集生命周期管理、DQ/QA 检查、accepted episode 导出，以及训练包生成。

当前正式版围绕一个原则设计：

```text
dataset action = follower-space effective_command = robot.send_action(command)
```

也就是说，训练数据里的 action 是 Workbench safety layer 后的真实 follower-space 指令，不是 master 原始动作，也不是 driver clamp 之后才被静默改写的动作。

## 4090 路径

```text
开发区：/home/sh/src/lerobot-openarm-workbench-dev
稳定区：/home/sh/lerobot_workbench
默认稳定端口：8091
默认开发端口：8092
```

稳定区用于正式采集。开发区用于继续开发、测试和代码提交。

## 稳定区启动

```bash
ssh groot-4090
cd /home/sh/lerobot_workbench
source /home/sh/miniforge3/bin/activate lerobot04
python scripts/start_workbench.py \
  --config config/workbench_config.phase1-hardware-test.json \
  --host 0.0.0.0 \
  --port 8091
```

浏览器打开：

```text
http://<4090-ip>:8091
```

如果 8091 已经被占用，先确认是否有旧工作台进程：

```bash
ps -ef | grep start_workbench.py | grep -v grep
```

## 核心能力

- 三路 RGB 相机实时监控，前端支持相机窗口大小、腕部行高、左右腕宽度调整。
- Move to Ready 与 Ready verification。
- Relative teleop Sync Master / Sync Left / Sync Right。
- Dry Teleop 方向检查。
- 正式采集 Start / Stop / Success / Failure / Discard。
- Workbench safety layer：
  - follower-space hard/soft limit；
  - max step / velocity limit；
  - driver mismatch 检测；
  - follower tracking warning / contamination / freeze。
- Safety Frozen UX：freeze 后明确禁用危险操作，自动保存 contaminated episode。
- Dataset lifecycle：
  - 新建 dataset root；
  - 切换 dataset root；
  - empty root 自动初始化；
  - legacy_unknown / semantic_mismatch 阻止继续写入。
- 采集批次 QA 报告。
- Task profile 管理。
- 训练包导出：
  - 只导出 `accepted=true + dq_status=pass + contaminated=false`；
  - episode index 连续；
  - 生成 `dataset_action_contract.json`、`export_report.json`、`export_provenance.json`；
  - 导出结果可被 `LeRobotDataset` 加载。

## 重要配置

主配置：

```text
/home/sh/lerobot_workbench/config/workbench_config.phase1-hardware-test.json
```

Ready 路径：

```text
/home/sh/lerobot_workbench/config/ready_path.json
```

Task profile 示例：

```text
/home/sh/lerobot_workbench/config/task_profiles/
```

采集数据常用 root：

```text
/tmp/lerobot-phase1-hardware-v2-verified/dataset
```

训练导出常用 root：

```text
/tmp/lerobot-phase1-hardware-v2-verified/<name>_training_export
```

## XLeRobot / SO101 v3

XLeRobot / SO101 双臂适配运行在新电脑 `so101-log`，不影响 OpenArm 8091。

```text
路径：/home/log/lerobot_workbench
端口：8093
URL：http://10.100.56.143:8093
配置：config/workbench_config.xlerobot_so101.json
数据：/home/log/data/xlerobot_so101_v1/dataset
保存策略：Stop 后延迟视频编码；导出/切换/关闭时完成 pending encoding
```

启动：

```bash
ssh so101-log
cd /home/log/lerobot_workbench
./run_xlerobot_workbench_8093.sh
```

详细 SOP：

```text
docs/SOP_XLEROBOT_SO101.md
```

当前 v3 verified 验收产物：

```text
collection dataset: /home/log/data/xlerobot_so101_v1/dataset
training export:    /home/log/data/xlerobot_so101_v1/exports/xlerobot_so101_v1_verified_export_20260702
QA report:          /home/log/data/xlerobot_so101_v1/reports/final_verified_20260702
```

## 完整操作说明

正式采集请看：

```text
docs/SOP_COLLECT_AND_EXPORT.md
```

里面包含：

- 启动/停机；
- 检查相机、机器人、遥操作；
- 记录 Ready 路径；
- 切换 Ready 路径；
- 新建/切换 dataset root；
- Move to Ready；
- Sync Master；
- Dry Teleop；
- 采集、标注、discard；
- Safety Frozen 后如何恢复；
- QA 报告；
- 训练包导出；
- 常见错误处理。

## 开发验证

在开发区运行：

```bash
cd /home/sh/src/lerobot-openarm-workbench-dev
source /home/sh/miniforge3/bin/activate lerobot04
PYTHONPATH=src python -m pytest -q
```

当前测试集覆盖 controller、dataset lifecycle、safety、ready/sync、QA、training export、前端静态资源等核心链路。

## Git / 部署约定

- 开发区提交代码。
- 稳定区只部署已验证版本。
- 不把 dataset、session、logs、tokens、模型权重提交进 git。
- 覆盖稳定区前必须跑完整测试。
- 覆盖稳定区后必须重新确认 8091 能启动，并检查 `/api/status`。

## Safety 语义摘要

采集链路：

```text
master_action_raw
→ compatibility mapping
→ follower-space action
→ Workbench safety layer
→ effective_command
→ dataset action
→ robot.send_action(effective_command)
→ LeRobot driver clamp 仅作为最后防线
```

如果 driver 仍然改写 command，Workbench 会记录 mismatch；超过阈值会污染 episode，阻止 accepted/export。

