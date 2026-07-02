# SO101 / XLeRobot 采集工作台使用手册

本文档面向实际采集人员，说明如何使用 `so101-log` 新电脑上的 SO101 / XLeRobot 双臂采集工作台完成数据采集、标注、QA 与训练包导出。

本手册只适用于 SO101 / XLeRobot 8093 工作台，不适用于 OpenArm 8091。

---

## 1. 基本信息

```text
机器：so101-log
Workbench 路径：/home/log/lerobot_workbench
浏览器地址：http://10.100.56.143:8093
配置文件：/home/log/lerobot_workbench/config/workbench_config.xlerobot_so101.json
Ready 配置：/home/log/lerobot_workbench/config/ready_path_xlerobot_so101.json

Collection dataset：/home/log/data/xlerobot_so101_v1/dataset
Session logs：       /home/log/data/xlerobot_so101_v1/sessions
Training exports：   /home/log/data/xlerobot_so101_v1/exports
QA reports：         /home/log/data/xlerobot_so101_v1/reports
历史归档：           /home/log/data/xlerobot_so101_v1/archive
```

当前 verified 语义：

```text
robot_profile_id = xlerobot_so101_dual_v1
robot.type = bi_so_follower
robot.id = xlerobot_follower
teleop.type = bi_so_leader
teleop.id = so101_leader

dataset_schema_version = xlerobot_so101_workbench_v1
action_schema_version = xlerobot_so101_action_v1
state_schema_version = xlerobot_so101_state_v1
camera_schema_version = xlerobot_so101_3rgb_v1
action_dim = 12
state_dim = 12
action_units = normalized_lerobot_motor_units
action_semantics = follower_effective_command
teleop_mode = relative_joint_offset

compat_mapping_version = so101_leader_to_xlerobot_follower_v1
compat_mapping_verified = true
safety_config_version = xlerobot_so101_safety_v1
safety_config_verified = true
```

---

## 2. 开始前检查

### 2.1 硬件检查

1. 机械臂电源已打开。
2. 四个串口设备连接正常：左右 follower、左右 leader。
3. 三个摄像头已插好：主视角、左腕、右腕。
4. 桌面环境和机械臂周围没有干涉物。
5. 浏览器建议使用 Safari / Chrome；如果某些国产浏览器打不开，优先换 Safari / Chrome。

### 2.2 网络检查

在 Mac 上检查：

```bash
ping 10.100.56.143
```

如果能 ping 通但打不开网页，检查 8093 是否启动：

```bash
nc -vz 10.100.56.143 8093
```

---

## 3. 启动工作台

登录 so101 电脑：

```bash
ssh so101-log
cd /home/log/lerobot_workbench
```

启动 8093：

```bash
./run_xlerobot_workbench_8093.sh
```

后台运行：

```bash
cd /home/log/lerobot_workbench
nohup ./run_xlerobot_workbench_8093.sh > /tmp/xlerobot_workbench_8093.log 2>&1 &
```

检查进程：

```bash
ps -eo pid,cmd | grep -E 'start_workbench.py.*8093' | grep -v grep
```

检查 API 状态：

```bash
curl -s http://127.0.0.1:8093/api/status \
  | /usr/bin/python3 -m json.tool \
  | head -120
```

正常状态应包含：

```text
robot.connected = true
teleop.connected = true
cameras.main.ok = true
cameras.wrist_left.ok = true
cameras.wrist_right.ok = true
compat_mapping_verified = true
safety_frozen = false
```

---

## 4. 打开网页

在浏览器打开：

```text
http://10.100.56.143:8093
```

页面主要区域：

- 左侧：三路相机画面；
- 右侧：任务描述、Ready/Sync 状态、核心控制、采集与标注、数据集、训练包导出、运行明细；
- 顶部：机器人、遥操作、相机等状态 chip。

---

## 5. 相机检查与路径修正

工作台固定使用三个 camera key：

```text
main
wrist_left
wrist_right
```

如果网页相机黑屏、启动失败或日志出现 `OpenCVCamera` / `No such device`，先枚举相机：

```bash
ls -l /dev/v4l/by-path/
/home/log/miniforge3/envs/lerobot/bin/lerobot-find-cameras opencv
```

也可以逐个读帧：

```bash
cd /home/log/lerobot_workbench
/home/log/miniforge3/envs/lerobot/bin/python - <<'PYCODE'
import cv2, time, os, glob
for path in sorted(glob.glob('/dev/video*')) + sorted(glob.glob('/dev/v4l/by-path/*')):
    ok = 0
    for _ in range(5):
        cap = cv2.VideoCapture(path, cv2.CAP_V4L2)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        cap.set(cv2.CAP_PROP_FPS, 30)
        ret = False
        for _ in range(10):
            ret, _ = cap.read()
            if ret:
                break
            time.sleep(0.03)
        cap.release()
        ok += int(ret)
    print(path, '->', os.path.realpath(path), f'{ok}/5')
PYCODE
```

修改路径：

```bash
cd /home/log/lerobot_workbench
nano config/workbench_config.xlerobot_so101.json
```

对应字段：

```json
"cameras": {
  "main": {"index_or_path": "/dev/v4l/by-path/...video-index0"},
  "wrist_left": {"index_or_path": "/dev/v4l/by-path/...video-index0"},
  "wrist_right": {"index_or_path": "/dev/v4l/by-path/...video-index0"}
}
```

注意：不要把电脑内置摄像头配置进数据集。改完后重启 8093。

---

## 6. Ready 位置

当前 SO101 v3 的 Ready 设计是 `current_pose`：

```json
{
  "mode": "current_pose",
  "waypoints": []
}
```

这表示：

- `Move to Ready` 不执行复杂轨迹；
- 它读取当前 follower 位置，并把当前点当作 ready；
- 适合 SO101 当前阶段，不需要像 OpenArm 那样维护复杂 ready path。

检查 Ready 配置：

```bash
cat /home/log/lerobot_workbench/config/ready_path_xlerobot_so101.json
```

如果未来要切换为真实轨迹 ready，需要先更新 PRD / 配置，再重新验收。

---

## 7. 标准采集流程

每轮正式采集按这个顺序执行。

### 7.1 填写任务描述

在网页右上角任务描述框输入真实 task prompt。不要使用默认文本。

### 7.2 Move to Ready

点击：

```text
Move to Ready
```

确认页面显示：

```text
Move to Ready：verified
```

如果失败，不要开始采集。先看日志或重新连接设备。

### 7.3 Sync Master

点击：

```text
Sync Master
```

确认页面显示类似：

```text
Sync Master：valid，arms=left+right，keys=12
```

如果 sync invalid，不要开始采集。

### 7.4 Dry Teleop

点击：

```text
Enable Dry Teleop
```

小幅移动主臂，确认方向和左右臂对应关系正确。Dry Teleop 不写入数据。

确认无误后可点击关闭 Dry Teleop；如果直接点 Start Recording，工作台也会自动关闭 Dry Teleop。

### 7.5 Start Recording

点击：

```text
Start Recording
```

开始采集后，按任务要求操作主臂。

### 7.6 Stop and Save

动作完成后点击：

```text
Stop and Save
```

SO101 8093 使用延迟视频编码：

```text
Stop and Save
→ 立即保存 episode parquet / metadata
→ 不等待三路 mp4 全量编码
→ Training export / Dataset switch / Workbench 正常关闭时完成 pending video encoding
```

状态接口中的 `dataset.video_encoding_pending_episodes` 表示仍待编码的 episode 数量。

### 7.7 标注

按实际结果点击：

```text
Success
Failure
Discard
```

规则：

- `success` 只表示任务结果成功；
- `accepted` 由后端根据 label、DQ、contamination、compat/safety verified 状态自动派生；
- 当前 verified 配置下，干净 episode 标记 success 后应得到 `accepted=true`；
- 如果出现 contamination 或 DQ fail，即使 label=success，也不会 accepted/export。

---

## 8. 数据集管理

当前默认 collection root：

```text
/home/log/data/xlerobot_so101_v1/dataset
```

如果需要新建测试数据集，可在 UI 的数据集区域使用新建/切换功能；也可以保守地在命令行归档旧 root 后重启：

```bash
cd /home/log/data/xlerobot_so101_v1
mkdir -p archive
mv dataset archive/dataset_$(date +%Y%m%d_%H%M%S)
```

然后重启 8093，工作台会重新初始化新的 dataset root。

不要把 SO101 数据 append 到 OpenArm dataset root，也不要把 OpenArm 数据 append 到 SO101 root。

如果看到 `dataset semantic mismatch` 或 `legacy_unknown`，说明当前 root 语义不匹配或不是受控 dataset。不要强行采集；请切换新 root 或归档旧 root。

---

## 9. QA 检查

生成 collection QA report：

```bash
cd /home/log/lerobot_workbench
PYTHONPATH=src /home/log/miniforge3/envs/lerobot/bin/python scripts/report_collection_batch.py \
  --root /home/log/data/xlerobot_so101_v1/dataset \
  --repo-id local/xlerobot_so101_v1 \
  --output /home/log/data/xlerobot_so101_v1/reports/$(date +%Y%m%d_%H%M%S)
```

重点检查：

```text
exportable_count > 0
driver_mismatch_count = 0
tracking_freeze_count = 0
timing_sidecar_missing_count = 0
```

最终 v3 验收 QA report：

```text
/home/log/data/xlerobot_so101_v1/reports/final_verified_20260702
```

---

## 10. Training Export

训练前不要直接拿 collection root 训练；应使用 training export 生成干净训练包。

UI 中使用“训练包导出”区域，填写：

```text
source_root:     /home/log/data/xlerobot_so101_v1/dataset
source_repo_id:  local/xlerobot_so101_v1
output_root:     /home/log/data/xlerobot_so101_v1/exports/<export_name>
output_repo_id:  local/<export_name>
config_file:     config/workbench_config.xlerobot_so101.json
```

导出规则：

```text
只导出 accepted=true + dq_status=pass + contaminated=false
导出后 episode index 连续
action_dim = 12
action_units = normalized_lerobot_motor_units
action_semantics = follower_effective_command
LeRobotDataset loader validation passed
```

导出包必须包含：

```text
dataset_action_contract.json
export_report.json
export_provenance.json
```

最终 v3 验收导出：

```text
/home/log/data/xlerobot_so101_v1/exports/xlerobot_so101_v1_verified_export_20260702
```

---

## 11. 命令行导出

如果不用 UI，也可以命令行导出：

```bash
cd /home/log/lerobot_workbench
PYTHONPATH=src /home/log/miniforge3/envs/lerobot/bin/python scripts/export_training_package.py \
  --source-root /home/log/data/xlerobot_so101_v1/dataset \
  --source-repo-id local/xlerobot_so101_v1 \
  --output-root /home/log/data/xlerobot_so101_v1/exports/so101_export_$(date +%Y%m%d_%H%M%S) \
  --output-repo-id local/so101_export \
  --config-file config/workbench_config.xlerobot_so101.json
```

导出后可独立 loader 检查：

```bash
PYTHONPATH=src /home/log/miniforge3/envs/lerobot/bin/python - <<'PYCODE'
from lerobot.datasets.lerobot_dataset import LeRobotDataset
root = '/home/log/data/xlerobot_so101_v1/exports/xlerobot_so101_v1_verified_export_20260702'
ds = LeRobotDataset('local/xlerobot_so101_v1_verified_export', root=root)
print(ds.num_episodes, ds.num_frames, ds.features.keys())
PYCODE
```

---

## 12. 停止 / 重启工作台

查看进程：

```bash
ps -eo pid,cmd | grep -E 'start_workbench.py.*8093' | grep -v grep
```

停止：

```bash
ps -eo pid,cmd | grep -E 'start_workbench.py.*8093' | grep -v grep | awk '{print $1}' | xargs -r kill
```

重启：

```bash
cd /home/log/lerobot_workbench
nohup ./run_xlerobot_workbench_8093.sh > /tmp/xlerobot_workbench_8093.log 2>&1 &
```

注意：不要在有 `video_encoding_pending_episodes > 0` 时直接断电或强杀。优先导出、切换数据集或正常停止，让 pending video encoding 完成。

---

## 13. 常见问题

### 13.1 网页打不开

检查：

```bash
ping 10.100.56.143
nc -vz 10.100.56.143 8093
ssh so101-log
```

如果 ping 通但 8093 不通，通常是工作台没启动或进程挂了，重启 8093。

### 13.2 `Port is in use`

说明串口被另一个进程占用，常见于重复启动 8093。杀掉多余进程后只保留一个 8093。

### 13.3 相机消失 / 黑屏

先重新插拔摄像头，再枚举 `/dev/v4l/by-path/`。如果路径变化，更新 `config/workbench_config.xlerobot_so101.json` 并重启。

### 13.4 Start Recording 失败

常见原因：

```text
Move to Ready 未 verified
Sync Master 未 valid
dataset semantic mismatch
safety_frozen=true
相机或机器人连接异常
```

先看页面状态区，再看日志：

```bash
tail -200 /tmp/xlerobot_workbench_8093.log
```

### 13.5 Stop 后保存看起来仍然慢

SO101 已经启用延迟视频编码。短 episode 仍可能有几秒钟用于 parquet / metadata / writer flush。长 episode 不应再等待完整三路 mp4 编码；真正的视频编码会延后到 export / switch / shutdown。

### 13.6 导出失败：metadata incomplete

说明 collection root 的 `dataset_manifest.json` 缺少 schema/profile 字段，通常来自旧版本或不完整测试 root。不要原地修训练数据；归档旧 root，新建 verified root 后重新采集。

---

## 14. 最终 v3 验收记录

2026-07-02 已完成 SO101 v3 验收：

```text
Move to Ready: verified, max_abs_error=0
Sync Master: valid, left+right, 12 keys
Dry Teleop: enable/disable passed
Final episode: episode 0, 180 frames, fps=29.94
Label: success
accepted=true
dq_status=pass
contaminated=false
driver_mismatch_count=0
tracking_warning_count=0
tracking_freeze_count=0
source videos: 3 cameras, 180 frames, 30 fps
training export: succeeded
LeRobotDataset loader validation: passed
pytest: 218 passed
commit: cde8d36 Finalize XLeRobot SO101 v3 workbench
```

最终产物：

```text
collection dataset:
/home/log/data/xlerobot_so101_v1/dataset

training export:
/home/log/data/xlerobot_so101_v1/exports/xlerobot_so101_v1_verified_export_20260702

QA report:
/home/log/data/xlerobot_so101_v1/reports/final_verified_20260702

static probe:
/home/log/data/xlerobot_so101_v1/reports/xlerobot_so101_probe_20260702.json
```
