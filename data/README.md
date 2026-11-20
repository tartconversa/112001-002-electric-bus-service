# 合成输入数据

用于线路和时段比较的合成车辆、班次、充电及维修记录。
所有记录均为虚构，仅供本地开发使用。日期与数值均为示例。

一个数据目录即一个**资料版本**；`corrections_2026_05/` 是在本目录
基础上补入晚到维修记录与缺失作业记录后的更正版本，用于演示
`compare` 对照。

## 文件与字段

- `vehicles.csv`：`vehicle_id, route_id, powertrain, battery_kwh, capacity,
  active_from, active_to`。`capacity` 为载客能力权重，电动化占比与可用
  运力均按它加权；`active_from/active_to` 为在役生效窗口（`active_to`
  可空）。
- `routes.csv`：`route_id, route_name, effective_from, effective_to`。
  同一线路可有多个生效区间不重叠的版本（线路调整），用于切分可比区间。
- `service.csv`：`trip_id, route_id, service_date, period, scheduled,
  completed, vehicle_id`。`scheduled > completed` 的差额即取消班次。
- `operations.csv`：`vehicle_id, date, charge_kwh, maintenance_minutes,
  reason`。同一车辆同一日可有多条记录（如晚到的维修记录），分别保留。
- `depot_constraints.csv`：`depot_id, route_id, period, charger_ports,
  available_kwh, assigned_vehicle_ids`。`assigned_vehicle_ids` 以 `|`
  分隔，为该场站时段登记可充电的车辆。
- `coverage_targets.csv`：`route_id, period, required_trips, is_peak,
  effective_from, effective_to`。按运营日 × 时段逐格核对的既定服务
  覆盖目标；`is_peak` 标记高峰时段。
