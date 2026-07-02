# SOP: XLeRobot / SO101 采集工作台 v3

本文档面向新电脑 `so101-log` 上的 XLeRobot / SO101 双臂采集工作台。它不替代 OpenArm 8091 SOP；两套工作台独立运行、独立配置、独立数据 root。

## 0. 路径与端口

```text
Workbench: /home/log/lerobot_workbench
URL:       http://10.100.56.143:8093
Dataset:   /home/log/data/xlerobot_so101_v1/dataset
Sessions:  /home/log/data/xlerobot_so101_v1/sessions
Exports:   /home/log/data/xlerobot_so101_v1/exports
Config:    /home/log/lerobot_workbench/config/workbench_config.xlerobot_so101.json
Ready:     /home/log/lerobot_workbench/config/ready_path_xlerobot_so101.json
```

OpenArm 8091 不使用这些 root；XLeRobot 8093 也不能 append 到 OpenArm dataset。

## 1. 启动 8093

```bash
ssh so101-log
cd /home/log/lerobot_workbench
./run_xlerobot_workbench_8093.sh
```

等价完整命令：

```bash
cd /home/log/lerobot_workbench
PYTHONPATH=src /home/log/miniforge3/envs/lerobot/bin/python scripts/start_workbench.py   --config config/workbench_config.xlerobot_so101.json   --host 0.0.0.0   --port 8093
```

检查状态：

```bash
curl -s http://127.0.0.1:8093/api/status | /home/log/miniforge3/envs/lerobot/bin/python -m json.tool | head -120
```

## 2. 相机检查与路径修正

工作台 schema 固定使用三个 camera key：

```text
main
wrist_left
wrist_right
```

当前配置使用 `/dev/v4l/by-path/...`，但如果 USB 口变化，by-path 也会变化。典型症状：8093 启动失败，日志出现：

```text
OpenCVCamera(...video-index0) read failed (status=False)
No such device
read thread is not running
```

枚举相机：

```bash
ls -l /dev/v4l/by-path/
/home/log/miniforge3/envs/lerobot/bin/lerobot-find-cameras opencv
```

连续读帧测试：

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
            ret, _frame = cap.read()
            if ret:
                break
            time.sleep(0.03)
        cap.release()
        ok += int(ret)
    print(path, '->', os.path.realpath(path), f'{ok}/5')
PYCODE
```

如果主视角路径变化，修改：

```text
/home/log/lerobot_workbench/config/workbench_config.xlerobot_so101.json
```

对应字段：

```json
"cameras": {
  "main": {"index_or_path": "/dev/v4l/by-path/...video-index0"},
  "wrist_left": {"index_or_path": "/dev/v4l/by-path/...video-index0"},
  "wrist_right": {"index_or_path": "/dev/v4l/by-path/...video-index0"}
}
```

修改后重启 8093。不要把内置摄像头 `/dev/video4` 配进 dataset。

## 3. Ready 语义

XLeRobot v3 当前 ready path 是 current-pose 模式：

```json
{
  "mode": "current_pose",
  "waypoints": []
}
```

Move to Ready 不执行复杂轨迹，只读取当前 follower 位置并验证当前点。

## 4. 正式采集顺序

浏览器打开：

```text
http://10.100.56.143:8093
```

推荐顺序：

1. 填写真实 task prompt，不要保留默认 `TODO: describe...`。
2. 点击 `Move to Ready`，确认 `verified`。
3. 点击 `Sync Master`，确认 `valid, arms=left+right, keys=12`。
4. 点击 `Enable Dry Teleop`，小幅移动主臂检查方向。
5. 如果方向正确，点击 `Start Recording`。
6. 完成动作后点击 `Stop and Save`。
7. 标注 `success` / `failure` / `discard`。

Dry Teleop 不写入数据；Start Recording 会自动关闭 dry teleop，并开始写 collection dataset。

### 4.1 保存速度与视频编码

XLeRobot 8093 默认采用延迟视频编码：

```text
Stop and Save
→ 立即保存 episode parquet / metadata
→ 暂不等待三路 mp4 全量编码
→ 后续 Training export / Dataset switch / Workbench shutdown 时完成 pending video encoding
```

这样可以避免长 episode 停止时卡几十秒。代价是：如果刚保存完就立刻导出、切换数据集或关闭工作台，这些动作会承担最后的视频编码时间。不要直接 kill 进程；需要退出时优先用正常停止脚本或让导出完成。

状态接口中的 `dataset.video_encoding_pending_episodes` 会显示当前仍待编码的 episode 数。

## 5. v3 数据语义

XLeRobot collection dataset 必须保持：

```text
dataset_schema_version = xlerobot_so101_workbench_v1
action_schema_version = xlerobot_so101_action_v1
state_schema_version = xlerobot_so101_state_v1
camera_schema_version = xlerobot_so101_3rgb_v1
action_dim = 12
state_dim = 12
action_units = normalized_lerobot_motor_units
action_semantics = follower_effective_command
teleop_mode = relative_joint_offset
```

控制链路：

```text
leader action
→ relative_joint_offset
→ XLeRobot compatibility mapping
→ Workbench safety
→ effective_command
→ dataset action
→ robot.send_action(effective_command)
```

## 6. 当前 v3 verified gate

当前 8093 已进入 verified 采集语义：

```text
compat_mapping_version = so101_leader_to_xlerobot_follower_v1
safety_config_version = xlerobot_so101_safety_v1
compat_mapping_verified = true
safety_config_verified = true
```

在 `Move to Ready` verified、`Sync Master` valid、episode DQ pass、且没有 contamination 时，`label=success` 会进入 `accepted=true`，可被 training export 导出。

历史 candidate / 不完整 manifest 测试数据已归档在：

```text
/home/log/data/xlerobot_so101_v1/archive
```

## 7. 短 episode 验收

验证 Phase E 时，采一条短 episode 后应检查：

```text
frame_count > min_episode_frames
fps 接近 30，不应被 save_duration 拉低
command_validation.mismatch_frames = 0
tracking_validation.freeze_frames = 0
三路 camera ok
parquet/video 对齐
dq_status = pass
accepted = true
```

如果发生相机中断，Workbench 会 abort 当前 episode 并清空 pending buffer。残留的 `images/.../episode-XXXXXX` 缓存不能训练，需要归档或删除。

## 8. Training export

verified 且存在 accepted episode 后，可从 UI 的训练包导出区域导出。当前最终验收导出路径：

```text
/home/log/data/xlerobot_so101_v1/exports/xlerobot_so101_v1_verified_export_20260702
```

导出包必须包含：

```text
dataset_action_contract.json
export_report.json
export_provenance.json
```

当前最终 QA report：

```text
/home/log/data/xlerobot_so101_v1/reports/final_verified_20260702
```

导出结果要求：

```text
只包含 accepted=true + dq_status=pass + contaminated=false
episode index 连续
action_dim = 12
action_units = normalized_lerobot_motor_units
LeRobotDataset loader validation passed
```

## 9. 常见问题

### 9.1 `dataset semantic mismatch`

说明当前 dataset root 的 manifest 与配置语义不一致。不要继续 append，切换新 root 或新建 dataset。

### 9.2 `Port is in use`

SO101 总线不能被多个读写线程同时访问。当前 Workbench 已对 Ready/Sync/teleop/control loop 做 device I/O 串行化；如果仍出现，先确认没有第二个 8093 或外部脚本占用设备。

### 9.3 `streaming_encoding unexpected keyword`

这是 LeRobot API 版本差异。当前兼容层已过滤 create/resume 不支持的参数；如果再次出现，说明正在运行旧进程，重启 8093。

### 9.4 相机 read failed / No such device

通常是 USB 口变化或摄像头链路不稳定。重新枚举 `/dev/v4l/by-path`，确认 config 中三路路径都能连续读帧。
