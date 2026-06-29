# SOP: OpenArm 采集工作台正式采集与导出

本文档面向 4090 上的稳定工作台。默认稳定区为：

```text
/home/sh/lerobot_workbench
```

默认稳定端口为：

```text
8091
```

## 0. 采集前原则

1. 正式采集只使用稳定区 8091。
2. 开发区 8092 可以用于测试新功能，但不要把正式数据混入开发测试 root。
3. 采集前必须完成：
   - 相机正常；
   - follower 机器人正常；
   - OpenArm mini 主臂正常；
   - Move to Ready verified；
   - Sync Master valid；
   - dataset root 状态 appendable 或新建成功。
4. 训练只使用导出的 training package，不直接用 collection dataset。
5. 如果发生 Safety Frozen，当前 episode 可以标注 success/failure/discard，但一定不会 accepted/export。

## 1. 启动稳定工作台

SSH 到 4090：

```bash
ssh groot-4090
```

启动 8091：

```bash
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

如果需要后台启动并保存日志：

```bash
cd /home/sh/lerobot_workbench
mkdir -p logs
nohup /home/sh/miniforge3/envs/lerobot04/bin/python scripts/start_workbench.py \
  --config config/workbench_config.phase1-hardware-test.json \
  --host 0.0.0.0 \
  --port 8091 \
  > logs/workbench_8091_$(date +%Y%m%d_%H%M%S).log 2>&1 &
```

查看是否启动：

```bash
curl -s http://127.0.0.1:8091/api/status | python -m json.tool | head -80
```

## 2. 停止工作台

先确认没有正在 recording：

```bash
curl -s http://127.0.0.1:8091/api/status | python -m json.tool | grep -A12 '"episode"'
```

停止进程：

```bash
ps -ef | grep 'start_workbench.py' | grep 8091 | grep -v grep
kill <pid>
```

不要在正在保存 episode 时强杀。

## 3. 检查硬件连接

### 3.1 CAN / follower

如果工作台启动失败，先看 CAN 和电源：

```bash
ip link show can0
ip link show can1
```

可用 LeRobot 工具测试：

```bash
lerobot-setup-can --mode=test --interfaces can0,can1
```

### 3.2 相机路径

查看相机：

```bash
lerobot-find-cameras opencv
```

或者：

```bash
ls -l /dev/v4l/by-path/
```

把稳定配置里的相机路径改到：

```text
/home/sh/lerobot_workbench/config/workbench_config.phase1-hardware-test.json
```

对应字段：

```json
"cameras": {
  "main": {"index_or_path": "..."},
  "wrist_left": {"index_or_path": "..."},
  "wrist_right": {"index_or_path": "..."}
}
```

改完重启 8091。

## 4. Ready 路径：查看、记录、切换

Ready 路径用于把 follower 移动到采集前的安全起始姿态。稳定区默认路径：

```text
/home/sh/lerobot_workbench/config/ready_path.json
```

配置入口：

```json
"ready": {
  "path": "/home/sh/lerobot_workbench/config/ready_path.json",
  "fps": 30,
  "tolerance": 2.0,
  "settle_time_s": 0.2,
  "verify_after_move": true,
  "require_ready_for_recording": true
}
```

### 4.1 查看当前 follower 位置

```bash
cd /home/sh/lerobot_workbench
source /home/sh/miniforge3/bin/activate lerobot04
python scripts/move_to_ready.py \
  --config config/workbench_config.phase1-hardware-test.json \
  --path config/ready_path.json \
  --print-current
```

注意：电源未开或 CAN 不通时会读不到位置。

### 4.2 记录单个 Ready 点

手动把 follower 从臂移动到想要的 ready 位置，然后执行：

```bash
cd /home/sh/lerobot_workbench
python scripts/move_to_ready.py \
  --config config/workbench_config.phase1-hardware-test.json \
  --path config/ready_path.json \
  --clear-path

python scripts/move_to_ready.py \
  --config config/workbench_config.phase1-hardware-test.json \
  --path config/ready_path.json \
  --capture-waypoint ready \
  --duration-s 3.0
```

这会清空旧路径，并记录一个名为 `ready` 的 waypoint。

### 4.3 记录多 waypoint Ready 轨迹

推荐先备份旧路径：

```bash
cp config/ready_path.json config/ready_path.json.backup_$(date +%Y%m%d_%H%M%S)
```

清空路径：

```bash
python scripts/move_to_ready.py \
  --config config/workbench_config.phase1-hardware-test.json \
  --path config/ready_path.json \
  --clear-path
```

依次手动移动 follower 到每个点，然后 capture：

```bash
python scripts/move_to_ready.py \
  --config config/workbench_config.phase1-hardware-test.json \
  --path config/ready_path.json \
  --capture-waypoint lift_clear_table \
  --duration-s 3.0

python scripts/move_to_ready.py \
  --config config/workbench_config.phase1-hardware-test.json \
  --path config/ready_path.json \
  --capture-waypoint ready_over_workspace \
  --duration-s 3.0
```

列出当前路径：

```bash
python scripts/move_to_ready.py \
  --config config/workbench_config.phase1-hardware-test.json \
  --path config/ready_path.json \
  --list-waypoints
```

### 4.4 dry-run 检查 Ready 路径

dry-run 不会发送真机动作：

```bash
python scripts/move_to_ready.py \
  --config config/workbench_config.phase1-hardware-test.json \
  --path config/ready_path.json \
  --execute \
  --dry-run
```

### 4.5 真机执行 Ready 路径

确认周围安全后：

```bash
python scripts/move_to_ready.py \
  --config config/workbench_config.phase1-hardware-test.json \
  --path config/ready_path.json \
  --execute \
  --yes
```

也可以在工作台 UI 点击 `Move to Ready`。UI 会执行并验证，成功后状态显示 ready verified。

### 4.6 切换 Ready 路径

做法一：改配置里的 `ready.path`，然后重启工作台。

例如准备两个路径：

```text
config/ready_path_pour_water.json
config/ready_path_grasp_can.json
```

修改：

```json
"ready": {
  "path": "/home/sh/lerobot_workbench/config/ready_path_pour_water.json"
}
```

做法二：通过 task profile 指定 `ready_path`。

示例：

```json
{
  "profile_name": "pour_water",
  "task_prompt": "...",
  "ready_path": "config/ready_path_pour_water.json",
  "dataset": {
    "root": "/tmp/pour_water_collection/dataset",
    "repo_id": "local/pour_water_collection",
    "session_root": "/tmp/pour_water_collection/sessions"
  },
  "teleop_mode": "relative_joint_offset",
  "safety_config_version": "openarm_follower_safety_v2"
}
```

注意：相对 `ready_path` 会基于 `workspace_root` 解析。稳定区的 `workspace_root` 应为：

```text
/home/sh/lerobot_workbench
```

如果误设成开发区，8091 会读到开发区路径。

## 5. Dataset root：新建、切换、语义检查

Workbench 对 dataset root 有 5 种状态：

1. root 不存在：可创建；
2. root 是空目录：可初始化；
3. root 非空且有 `dataset_manifest.json`：语义一致才可 append；
4. root 非空但无 manifest：`legacy_unknown`，禁止 append/export；
5. root 有 manifest 但语义不一致：`semantic_mismatch`，禁止 append。

### 5.1 UI 新建数据集

在右侧 `数据集` 面板填写：

```text
root
repo_id
session_root
```

点击 `创建新数据集`。

建议每轮正式任务使用新的 root，例如：

```text
/tmp/lerobot-pour-water-20260629/dataset
/tmp/lerobot-pour-water-20260629/sessions
local/pour_water_20260629
```

### 5.2 UI 切换数据集

在 `数据集` 面板填写目标 root/repo/session root，点击 `切换数据集`。

如果提示：

```text
dataset semantic mismatch for teleop_mode: expected 'relative_joint_offset', got 'absolute_passthrough'
```

说明该 root 是旧语义或其他模式采出来的数据，不能继续混采。请新建 root，不要强行 append。

### 5.3 命令行检查 dataset status

```bash
curl -s http://127.0.0.1:8091/api/dataset/status | python -m json.tool
```

确认：

```text
can_append: true
root_state: appendable
```

或者 root 不存在/空目录时，通过 UI 创建。

## 6. 正式采集流程

### 6.1 采集前检查

打开 8091 页面后确认顶部状态：

```text
机器人正常
遥操作正常
主视角正常
左腕正常
右腕正常
```

右侧状态确认：

```text
就绪：valid / verified
同步：valid
遥操作：按需启用
冻结：正常
```

### 6.2 Move to Ready

点击：

```text
Move to Ready
```

成功后应显示类似：

```text
Move to Ready：verified，max_error=<数值>
```

如果失败：

1. 检查 ready path 是否存在；
2. 检查 robot 电源/CAN；
3. 检查路径是否越界；
4. 查看 8091 终端日志。

### 6.3 Sync Master

让主臂处于和 follower ready 对应的姿态，点击：

```text
Sync Master
```

成功后：

```text
Sync Master：valid，arms=left+right，keys=16
```

如果只想同步单臂，可使用：

```text
Sync Left
Sync Right
```

### 6.4 Dry Teleop

点击：

```text
Dry Teleop
```

小幅移动主臂，确认方向正确。Dry Teleop 不写数据。

检查完关闭 Dry Teleop。

### 6.5 Enable Teleop

点击：

```text
Enable Teleop
```

确认 follower 随主臂小幅运动正常，没有明显反向或抖动。

### 6.6 开始采集

确认任务文本正确后，点击：

```text
开始采集
```

采集中不要切换 dataset、不要改 ready path、不要刷新页面。

### 6.7 停止并保存

动作完成后点击：

```text
停止并保存
```

等待页面提示 episode 已保存。

### 6.8 标注

根据实际任务结果点击：

```text
标记成功
标记失败
丢弃本段
```

注意：

- label 可以是 success；
- accepted 由后端根据 DQ、安全、污染状态自动派生；
- 如果 safety_config、DQ、tracking、mismatch 不通过，即使 label=success，accepted 也会是 false；
- discard 永远不会 accepted/export。

## 7. Safety Frozen 处理

如果采集中触发 follower tracking freeze：

```text
Safety Frozen
```

Workbench 会：

1. 自动 stop/save 当前 episode；
2. 标记 contaminated；
3. `dq_status=fail`；
4. `accepted=false`；
5. 禁用 Start / Move to Ready / Sync / Teleop / Dataset switch。

你可以标注 success/failure/discard，但该 episode 不会进入训练导出。

恢复流程：

1. 停止工作台；
2. 检查真机状态和周围环境；
3. 重新启动 8091；
4. Move to Ready；
5. Sync Master；
6. 再开始下一段采集。

如果进入 `frozen_error`，不要继续采集；先保留日志和 session，人工排查。

## 8. QA 报告

采完一批后，在 UI 的 QA/报告区域生成采集批次 QA 报告。

也可以通过脚本或测试工具检查：

```bash
cd /home/sh/lerobot_workbench
find /tmp -name 'collection_qa_report.json' -o -name '*qa*.json' | sort
```

重点看：

```text
accepted episode 数量
dq_status
contaminated
driver mismatch
tracking warning/contamination/freeze
camera frame 对齐
timing/fps
```

只有 clean accepted episode 才能进入训练包。

## 9. 训练包导出

### 9.1 UI 导出

在工作台右侧 `训练包导出` 面板填写：

```text
source root：当前 collection dataset root
source repo_id：当前 collection repo_id
output root：新的 training export root
output repo_id：新的 training export repo_id
```

点击导出。

导出器会：

1. 不修改 source dataset；
2. 只导出 `accepted=true + dq_status=pass + contaminated=false`；
3. 重写 episode index，保证连续；
4. 保持 `action_semantics=follower_effective_command`；
5. 写入：
   - `dataset_action_contract.json`
   - `export_report.json`
   - `export_provenance.json`
6. 用 LeRobotDataset loader 验证导出结果。

### 9.2 命令行 dry-run

```bash
cd /home/sh/lerobot_workbench
python scripts/export_training_package.py \
  --source-root /tmp/lerobot-phase1-hardware-v2-verified/dataset \
  --source-repo-id local/phase1_safety_hardware_test_v2_verified \
  --output-root /tmp/lerobot-phase1-hardware-v2-verified/dataset_training_export \
  --output-repo-id local/phase1_safety_hardware_training_export \
  --config-file config/workbench_config.phase1-hardware-test.json \
  --dry-run
```

### 9.3 命令行正式导出

```bash
python scripts/export_training_package.py \
  --source-root /tmp/lerobot-phase1-hardware-v2-verified/dataset \
  --source-repo-id local/phase1_safety_hardware_test_v2_verified \
  --output-root /tmp/lerobot-phase1-hardware-v2-verified/dataset_training_export \
  --output-repo-id local/phase1_safety_hardware_training_export \
  --config-file config/workbench_config.phase1-hardware-test.json
```

如果 output root 已存在，为避免覆盖旧训练包，建议换新名字，例如：

```text
dataset_training_export_20260629_001
```

## 10. 导出后检查

检查文件：

```bash
ls -la /tmp/lerobot-phase1-hardware-v2-verified/dataset_training_export
ls -la /tmp/lerobot-phase1-hardware-v2-verified/dataset_training_export/meta
```

必须有：

```text
dataset_action_contract.json
export_report.json
export_provenance.json
meta/info.json
meta/episodes.jsonl
data/
videos/
```

检查 action contract：

```bash
cat /tmp/lerobot-phase1-hardware-v2-verified/dataset_training_export/dataset_action_contract.json | python -m json.tool
```

应包含：

```text
action_semantics = follower_effective_command
```

检查 LeRobotDataset 可加载：

```bash
python - <<'PY'
from lerobot.datasets import LeRobotDataset
ds = LeRobotDataset(
    "local/phase1_safety_hardware_training_export",
    root="/tmp/lerobot-phase1-hardware-v2-verified/dataset_training_export",
)
print(ds)
print("episodes:", ds.num_episodes)
PY
```

## 11. 常见问题

### 11.1 开始采集失败：semantic mismatch

现象：

```text
dataset semantic mismatch for teleop_mode
```

处理：

1. 不要继续写这个 root；
2. 在 UI 新建一个 dataset root；
3. 或切换到语义一致的 root；
4. 旧 root 可保留为证据，但不要混入训练。

### 11.2 空目录 FileExistsError

正式版会把 empty root 当作可初始化状态，不应暴露 LeRobot 的 `FileExistsError`。如果仍看到该错误，说明跑的不是正式版或配置指向旧代码。

### 11.3 Move to Ready 用错路径

检查：

```bash
cat /home/sh/lerobot_workbench/config/workbench_config.phase1-hardware-test.json | grep -A8 '"ready"'
cat /home/sh/lerobot_workbench/config/workbench_config.phase1-hardware-test.json | grep workspace_root
```

稳定区应为：

```text
workspace_root=/home/sh/lerobot_workbench
ready.path=/home/sh/lerobot_workbench/config/ready_path.json
```

### 11.4 相机打不开

重新查路径：

```bash
lerobot-find-cameras opencv
ls -l /dev/v4l/by-path/
```

更新配置后重启 8091。

### 11.5 Stop 后页面像没反应

如果发生 freeze，Workbench 可能已经自动保存并进入 Safety Frozen。看顶部红色警告和 status：

```bash
curl -s http://127.0.0.1:8091/api/status | python -m json.tool | grep -A20 safety_frozen
```

## 12. 正式采集 checklist

每次正式采集前：

- [ ] 8091 是稳定区 `/home/sh/lerobot_workbench` 启动的；
- [ ] 三路相机正常；
- [ ] robot connected；
- [ ] teleop connected；
- [ ] dataset root appendable 或新建成功；
- [ ] task prompt 正确；
- [ ] Move to Ready verified；
- [ ] Sync Master valid；
- [ ] Dry Teleop 方向正确；
- [ ] Enable Teleop 后跟随正常；
- [ ] 开始采集；
- [ ] 停止并保存；
- [ ] 标注 success/failure/discard；
- [ ] 批次 QA；
- [ ] 导出 training package；
- [ ] 检查 `dataset_action_contract.json`、`export_report.json`、`export_provenance.json`；
- [ ] LeRobotDataset loader 可加载导出 root。

