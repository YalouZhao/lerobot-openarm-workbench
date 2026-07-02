# PRD：LeRobot 采集工作台 v3 — XLeRobot / SO101 双臂适配

## 0. 一句话目标

在不影响现有 OpenArm 稳定采集系统的前提下，为采集工作台新增一套独立的 XLeRobot / SO101 双臂采集配置，使其支持：

```text
SO101 leader 双主臂
→ XLeRobot / SO101-compatible follower 双从臂
→ relative_joint_offset 遥操作
→ Workbench safety
→ effective_command
→ collection dataset
→ accepted gate
→ training package export
```

核心约束：

```text
dataset action = effective_command = robot.send_action(effective_command)
```

本 PRD 只关注采集工作台，不涉及外部模型执行链路。

---

## 1. 现场部署事实

XLeRobot 新机械臂部署在新电脑 `so101-log`，实际用户为 `log`。

Workbench 路径：

```text
/home/log/lerobot_workbench
```

XLeRobot 数据路径统一使用：

```text
/home/log/data/xlerobot_so101_v1/dataset
/home/log/data/xlerobot_so101_v1/sessions
/home/log/data/xlerobot_so101_v1/exports
```

旧 OpenArm 4090 的 `/home/sh/...` 路径只保留在 OpenArm 稳定区说明中，不得用于 XLeRobot 配置示例。

端口与访问：

```text
OpenArm stable：8091
XLeRobot / SO101：so101-log 新电脑 8093
开发区：8092
XLeRobot URL：http://10.100.56.143:8093
```

v3 第一阶段不做 UI 内机械臂热切换。XLeRobot 通过 8093 独立启动。

启动命令：

```bash
cd /home/log/lerobot_workbench
./run_xlerobot_workbench_8093.sh
```

等价完整命令：

```bash
cd /home/log/lerobot_workbench
PYTHONPATH=src /home/log/miniforge3/envs/lerobot/bin/python scripts/start_workbench.py \
  --config config/workbench_config.xlerobot_so101.json \
  --host 0.0.0.0 \
  --port 8093
```

---

## 2. 不影响旧 OpenArm

v3 不允许：

```text
修改 OpenArm 稳定配置
复用 OpenArm dataset root
复用 OpenArm ready path
复用 OpenArm safety_config_version
复用 OpenArm action schema
把 XLeRobot 数据 append 到 OpenArm dataset root
```

OpenArm v2 稳定配置继续保留，8091 不受 8093 影响。

---

## 3. robot_profile_id 与 LeRobot calibration id 分离

Workbench / dataset / export 使用：

```text
robot_profile_id = xlerobot_so101_dual_v1
```

LeRobot driver / calibration 使用当前已验证 id：

```text
robot.type = bi_so_follower
robot.id = xlerobot_follower
teleop.type = bi_so_leader
teleop.id = so101_leader
```

不得把 `robot_profile_id` 直接写入 `robot.id`。否则 LeRobot BiSO wrapper 会把 calibration id 拼成不存在的：

```text
xlerobot_so101_dual_v1_left
xlerobot_so101_dual_v1_right
```

正确 calibration id 应保持：

```text
xlerobot_follower_left
xlerobot_follower_right
so101_leader_left
so101_leader_right
```

---

## 4. 数据语义与 schema

XLeRobot 必须使用新的 Workbench schema：

```text
dataset_schema_version = xlerobot_so101_workbench_v1
action_schema_version = xlerobot_so101_action_v1
state_schema_version = xlerobot_so101_state_v1
camera_schema_version = xlerobot_so101_3rgb_v1
action_dim = 12
state_dim = 12
action_units = normalized_lerobot_motor_units
state_units = normalized_lerobot_motor_units
action_semantics = follower_effective_command
action_space = joint_position
control_mode = joint_position_target
```

不得使用：

```text
openarm_workbench_v2
openarm_follower_safety_v2
OpenArm 旧 16 维 action
right-first OpenArm 顺序
degrees
raw encoder tick
```

`action_names` 与 `state_names` 均采用 left-first 顺序：

```text
left_shoulder_pan.pos
left_shoulder_lift.pos
left_elbow_flex.pos
left_wrist_flex.pos
left_wrist_roll.pos
left_gripper.pos
right_shoulder_pan.pos
right_shoulder_lift.pos
right_elbow_flex.pos
right_wrist_flex.pos
right_wrist_roll.pos
right_gripper.pos
```

训练数据 action 的含义：

```text
XLeRobot follower 坐标系下、normalized LeRobot motor units 中的最终有效关节目标命令。
```

---

## 5. LeRobot Dataset API 表述

PRD 中不得混用 “Workbench v3” 和 “LeRobot dataset v3”。

统一表述为：

```text
collection dataset 使用当前安装版 LeRobot Dataset API 写入；
Workbench schema version = xlerobot_so101_workbench_v1。
```

如果后续训练工具需要其他格式，另走转换 / 导出流程，不在采集源 dataset 上原地修改。

---

## 6. Camera mapping 现场修正

Workbench camera key 仍固定为：

```text
main
wrist_left
wrist_right
```

实际设备映射以 `so101-log` 枚举为准。当前现场实测：

```text
/dev/video0 = 主视角
/dev/video2 = 腕部视角
/dev/video6 = 腕部视角
/dev/video4 = 内置摄像头，不用
```

长期配置必须优先使用稳定路径：

```text
/dev/v4l/by-path/...
```

不得依赖 `/dev/videoX` 永远稳定不变。

当前配置中 camera key 到具体左右腕部的归属，必须以现场画面确认后写入 config；如相机位置交换，只允许改 camera config，不允许改 dataset schema key。

---

## 7. Teleop / Sync / control chain

v3 使用：

```text
teleop_mode = relative_joint_offset
```

同步时：

```text
leader_start = 当前 leader normalized joint position
follower_start = 当前 follower normalized joint position
action_offset = follower_start - leader_start
```

遥操作时：

```text
follower_goal = leader_action + action_offset
```

或等价写成：

```text
follower_goal = follower_start + gain * (leader_now - leader_start)
```

标准控制链路：

```text
leader_action_raw
→ SO101 compatibility / normalization
→ relative_joint_offset
→ follower-space target
→ Workbench safety layer
   - deadband
   - soft limit
   - max step
   - max velocity
   - hard limit
→ effective_command
→ dataset action
→ robot.send_action(effective_command)
→ driver clamp 仅作为最后防线
```

v3 默认强制：

```text
require_ready_for_recording = true
require_sync_for_recording = true
sync.required_arms = ["left", "right"]
```

支持：

```text
Sync Master = both
Sync Left
Sync Right
```

recording 中请求 Sync 必须拒绝执行，并污染当前 episode：

```text
contamination_reason = relative_resync_during_recording
accepted=false
export blocked
```

---

## 8. Compatibility mapping

新增 mapping candidate：

```text
compat_mapping_version = so101_leader_to_xlerobot_follower_v1_candidate
compat_mapping_verified = false
```

实机验证通过后升级为：

```text
compat_mapping_version = so101_leader_to_xlerobot_follower_v1
compat_mapping_verified = true
```

初始假设：

```text
SO101 leader 与 XLeRobot follower 使用相同 normalized joint names
body joints 范围 [-100, 100]
gripper 范围 [0, 100]
relative_joint_offset 可直接工作
```

但该假设不得直接视为 verified。

必须逐 joint 实机验证方向、幅度、左右臂不串臂、gripper open/close 语义、sync 后 follower 不跳变。若发现符号反转、gripper 反向、left/right 镜像问题，必须写入 mapping rule，并升级 mapping version。

---

## 9. Safety config

v3 不允许复用：

```text
openarm_follower_safety_v2
```

新增：

```text
safety_config_version = xlerobot_so101_safety_v1_candidate
safety_config_verified = false
```

实机验收后升级为：

```text
safety_config_version = xlerobot_so101_safety_v1
safety_config_verified = true
```

Candidate limits：

```text
body joints clamp: [-100, 100]
gripper clamp: [0, 100]
ARM_MAX_RELATIVE_TARGET = 15.0 per 30Hz tick
GRIPPER_MAX_RELATIVE_TARGET = 35.0 per 30Hz tick
```

这些限制必须在 Workbench safety layer 中实现，不得只依赖 driver clamp。

tracking thresholds 待实机确认：

```text
tracking_error_warning
tracking_error_contamination
tracking_error_freeze
driver_mismatch_atol
mismatch_contamination_frames
ready tolerance
```

单位必须是：

```text
normalized_lerobot_motor_units
```

不得沿用 OpenArm degree 阈值。

Safety Frozen 语义保持现有行为：

```text
recording=false
safety_frozen=true
ready_valid=false
sync_valid=false
episode contaminated
dq_status=fail
accepted=false
export blocked
```

---

## 10. Driver mismatch 与待确认 driver 行为

v3 必须继续检测：

```text
effective_command
vs
driver returned command / observed command
```

如果 SOFollower `send_action()` 不返回实际 command，则使用 Workbench `effective_command` 作为 sent command，并通过下一帧 follower state 监控 tracking error。

开发前必须实测：

```text
send_action 是否内部 clamp
越界时是报错还是静默裁剪
是否返回实际发送值
是否返回 None
读取 state 的频率和延迟
SOFollower / SOLeader 实际返回 feature keys
```

如果 driver 静默 clamp，Workbench safety 必须提前覆盖相同 clamp，保证 dataset action 仍等于 effective_command。

---

## 11. Ready path

v3 新增独立 ready path：

```text
/home/log/lerobot_workbench/config/ready_path_xlerobot_so101.json
```

不得使用 OpenArm 的：

```text
config/ready_path.json
```

Ready 使用 follower normalized joint position：

```text
ready_units = normalized_lerobot_motor_units
```

必须支持：

```text
record current follower pose
capture waypoint
execute dry-run
execute real move
verify final pose
```

ready 未验证时禁止 recording。

---

## 12. Dataset lifecycle 与 metadata

XLeRobot 必须使用独立 dataset root：

```text
/home/log/data/xlerobot_so101_v1/dataset
```

只要以下任一字段不同，禁止 append：

```text
dataset_schema_version
robot_profile_id
robot_family
robot_model
robot_driver
teleop_driver
action_schema_version
state_schema_version
camera_schema_version
action_semantics
action_names
action_units
teleop_mode
compat_mapping_version
safety_config_version
```

v3 dataset metadata 必须新增或写入：

```text
robot_profile_id = xlerobot_so101_dual_v1
robot_family = so101_compatible
robot_model = xlerobot
robot_driver = SOFollower
teleop_driver = SOLeader
dataset_schema_version = xlerobot_so101_workbench_v1
action_schema_version = xlerobot_so101_action_v1
state_schema_version = xlerobot_so101_state_v1
camera_schema_version = xlerobot_so101_3rgb_v1
action_dim = 12
state_dim = 12
action_units = normalized_lerobot_motor_units
state_units = normalized_lerobot_motor_units
```

---

## 13. Training export / action contract / QA 泛化

XLeRobot training export 必须沿用 production export 原则：

```text
不原地修改 source dataset
只导出 accepted=true + dq_status=pass + contaminated=false
导出后 episode index 连续
action_semantics 保持 follower_effective_command
导出结果可被 LeRobotDataset loader 加载
```

`dataset_action_contract.json` 必须使用：

```text
contract_version = xlerobot_so101_dataset_action_contract_v1
```

Contract 必须明确声明：

```text
The action column is the follower-space effective command in normalized LeRobot motor units after relative_joint_offset and Workbench safety processing.
```

training export、dataset_action_contract、QA report、accepted/export gate 不得 hardcode：

```text
openarm_workbench_v2
openarm_follower_safety_v2
16 维 action
degrees
right-first OpenArm 顺序
```

QA report 必须支持：

```text
robot_profile_id
robot_model
action_schema_version
state_schema_version
camera_schema_version
safety_config_version
compat_mapping_version
action_dim
state_dim
camera_keys
```

---

## 14. DQ gate / accepted gate

v3 继续沿用现有 DQ gate。

episode 必须满足：

```text
label == success
accepted == true
dq_status == pass
contaminated == false
dataset_schema_version == xlerobot_so101_workbench_v1
action_semantics == follower_effective_command
safety_config_verified == true
compat_mapping_verified == true
ready_verified == true
sync_valid_at_record_start == true
driver mismatch within threshold
metadata complete
```

才允许进入 training package export。

---

## 15. 当前阶段状态

当前状态标记：

```text
Phase 0 基本完成
Phase B 部分完成
```

已完成或已验证：

```text
so101-log 可 SSH 连接
/home/log/lerobot_workbench 已部署
8093 可启动
robot connected
teleop connected
三路 RGB camera connected
XLeRobot 独立 config / dataset root / session root / export root 已创建
OpenArm 8091 未受影响
```

后续必须继续补：

```text
robot_profile metadata manifest/export/report 全链路写入
SO101 actual feature keys 打印确认
send_action clamp / return 行为确认
mapping candidate TDD
safety candidate TDD
ready/sync/dry teleop 实机验收
short episode + training export validation
```

---

## 16. v3 实施阶段

Phase A：Schema / Profile Freeze

```text
冻结 action/state/camera schema
冻结 robot_profile_id 与 LeRobot id 分离规则
冻结 dataset lifecycle / accepted-export gate 规则
```

Phase B：Config + Driver Adapter 接入

```text
config/workbench_config.xlerobot_so101.json
SOFollower / SOLeader config adapter
feature builder 支持 12 维 normalized schema
camera config 支持 main / wrist_left / wrist_right
connect/read/send_action smoke test
```

Phase C：Mapping + Safety TDD

```text
so101_leader_to_xlerobot_follower mapping
xlerobot_so101_safety_v1_candidate
hard/soft clamp
max step
max velocity
driver mismatch
tracking warning/contamination/freeze
unit tests
```

Phase D：Ready / Sync / Dry Teleop 实机验证

```text
连接 8093
检查 camera
记录 ready path
Move to Ready dry-run
Move to Ready real
Sync Master
Sync Left
Sync Right
Enable Dry Teleop
逐 joint 小幅动作验证
```

Phase E：短 episode + DQ gate

```text
dataset action = effective_command
state/action 12 维
三路视频写入正常
parquet/video 对齐
timing sidecar 生成
dq_status=pass
accepted gate 正常
training export gate 正常
```

Phase F：Training Export + Loader Validation

```text
training package export succeeded
dataset_action_contract.json 存在
export_report.json 存在
export_provenance.json 存在
LeRobotDataset loader validation passed
action_dim=12
action_units=normalized_lerobot_motor_units
episode index 连续
source dataset 未被修改
```

Phase G：稳定区隔离部署

```text
OpenArm 8091 可正常启动
XLeRobot 8093 可正常启动
两者 config / dataset root 不混用
Git commit 完成
README / SOP 更新
```

Phase H：Robot Profile UI，后置可选，不在 v3 第一阶段实现。

---

## 17. v3 验收通过定义

XLeRobot v3 只有同时满足以下条件，才能认为通过：

```text
OpenArm 8091 不受影响
XLeRobot 8093 可独立启动
robot connected
teleop connected
三路 camera 正常
Move to Ready verified
Sync valid left+right
relative teleop 方向正确
dataset_schema_version = xlerobot_so101_workbench_v1
action_dim = 12
action_units = normalized_lerobot_motor_units
dataset action = effective_command
driver mismatch within threshold
safety_config_verified = true
compat_mapping_verified = true
短 episode dq_status=pass
accepted=true
training package export succeeded
dataset_action_contract.json 正确
LeRobotDataset loader validation passed
README / SOP 更新
Git commit 完成
```
