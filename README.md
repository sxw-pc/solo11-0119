# 农田病株隔离采录台

离线采录病株位置与田块边界，发布隔离范围、复查记录与植株转运决定。三个独立入口为 `observation-import`、`zone-plan`、`movement-import`；各自保存原始证据、业务实体、状态和跨链决定。所有数据为离线合成 fixture，不访问网络。

安装：`python -m pip install . --no-deps --no-build-isolation`。演示：`python -m cropquarantine demo`。测试：`python -m pytest -q`。各入口接受 `--db` 和 `--file`；`report --db` 输出逐实体状态与来源。

病株点必须落在冻结田块内；`diagnose-import` 保存独立复核，确诊或驳回会改变下次隔离规划采用的阳性点。隔离范围按点到田块边界的最短距离传播，两个晚于阳性的阴性复查可解除，随后阳性复查会重新激活。转运申请会引用当时隔离版本；已出运批次因迟到阳性复核被撤销许可时形成 recall_required，`return-import` 仅在整批封签实物返回后关单。zone 与 movement_event 保留旧结论；`demo-decisions` 运行准运→出运→迟到阳性召回→整批退回的闭环。

田间后续采录另有三个互不代替的入口。`lab-import` 保存带阴性/阳性对照的实验批次和样本判读，`diagnose-import` 可引用可信样本作为确诊或驳回的依据；`treatment-import` 登记已出现阳性观察的田块上合成制剂、作物适配、面积比例和剂量；`staff-import` 记录人员在田块的入出时刻，活动隔离区只允许检查目的入田。样例与对应冲突文件在 fixtures，三个入口均可独立重跑和从 report 查看原始来源与决定。制剂、阈值和人员规则仅用于合成离线演示。

喷施证据在面积比例之外再补两个入口。`spray-import` 保存校准证书（实际剂量倍率闭区间）和田块内矩形喷施片段（时刻、制剂、名义单位面积剂量、喷头号），单田至多六个片段、八个阳性点；同一张校准证书的片段共享同一倍率区间，剂量界限只由该区间推出，不能逐片挑选有利倍率。几何评估把边界接触与有面积覆盖严格区分：片段必须在田块内部有面积，田块之外的面积不参与任何稀释；重叠区按真实共同倍率累加剂量，任何位置超过制剂上限即记 definite 超量并拒签，仅在倍率不确定时可能超量记 risk 待复核。`certificate-import` 受理 `local`（已确诊病株所在小区）或 `whole_plot`（整块田）申请：病株全部确定覆盖而其余田面留白时小区证书可签发、整田证书以 plot_not_fully_covered 拒签，适用范围印在证书的 printed_scope/applicable_scope 上。病株点带测量误差半径时，用误差盘内所有可达位置与所有相容倍率核验：全部落在制剂有效上下限内才是 confirmed_covered，全部不满足为 failed，其余为 review；零半径点恰好落在片段边界只算 boundary_contact、不算覆盖。晚到确诊或驳回只重算未签发申请，已签发处置单保留原观察、喷施与校准证据，若新证据使其不再充分则另记 certificate_followup（recheck_required），不静默抹除。report 的 spray_evaluation 给出每个病株的剂量界限、重叠超量区域、留白单元与证书适用范围。
