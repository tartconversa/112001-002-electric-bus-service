# 电动公交运营分析

按**可比运营区间**联合呈现车辆电动化、实际运力、服务可靠性与能源表现，
避免“排放强度下降”掩盖削减班次、缩短服务时段或剔除故障车辆等代价。

## 运行环境

需要 Python 3.11 或更新版本。项目仅使用 Python 标准库。

## 快速开始

```bash
# 校验数据集结构与引用完整性
python -m transit_analysis validate --data data

# 按线路与可比区间输出联合指标（--detail 展开班次/车辆/例外，--json 输出机读结果）
python -m transit_analysis report --data data --detail

# 对照两个资料版本：原始观测 vs 晚到更正后的解释
python -m transit_analysis compare --data data --other data/corrections_2026_05

# 评估调度方案对高峰班次、服务覆盖与各线路指标的共同影响
python -m transit_analysis propose --data data --proposal examples/proposal_replace_b02.json

# 留存选定方案及其采用的资料版本，供下月复核
python -m transit_analysis save --data data --proposal examples/proposal_replace_b02.json
python -m transit_analysis review
```

## 口径设计

- **取消班次不计入效率提升**：零排放占比与排放强度同时给出“占完成服务”
  与“占计划服务”两个口径。削减班次只能美化前者，无法美化后者；
  两者并列即暴露以服务为代价的“改善”。
- **运力按载客能力加权**：不同电池容量与车型不按车辆台数直接比较，
  电动化占比、可用运力均按车辆 `capacity` 加权。
- **换车与停驶影响相应时段运力**：在役窗口（`active_from`/`active_to`）
  之外的车辆不计入可用运力；维修分钟按当日理论运营分钟折算扣减。
- **可比区间**：日历月 × 线路版本切分。线路调整会切开区间并打上
  `ROUTE_CHANGE_BOUNDARY` 标记；数据缺失（有班次但无充电/维修记录）
  打上 `PROVISIONAL_DATA` 暂定标记，不按零处理。
- **资料版本**：一个数据目录即一个版本。晚到的维修记录、补齐的缺失
  数据以新版本目录存放，`compare` 同时保留原始观测与更正后的解释。
- **方案校验**：充电安排受场站接口数与时段电量约束；同一车辆同一时段
  不得重复排入两个班次，也不得同时充电与出勤；车辆替换/停驶自生效
  日期起改变可用运力，未改派的班次记为风险班次并核对服务覆盖目标。

## 本地验证

```bash
python -m unittest discover -s tests -v   # 单元测试
python -m compileall -q tests             # 语法检查
```

## 数据说明

`data/` 目录包含少量合成输入记录，字段口径见 `data/README.md`；
`data/corrections_2026_05/` 为晚到更正后的资料版本示例；
`examples/` 为调度方案示例。
