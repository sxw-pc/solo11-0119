# 农田病株隔离采录台

离线采录病株位置与田块边界，发布隔离范围、复查记录与植株转运决定。三个独立入口为 `observation-import`、`zone-plan`、`movement-import`；各自保存原始证据、业务实体、状态和跨链决定。所有数据为离线合成 fixture，不访问网络。

安装：`python -m pip install . --no-deps --no-build-isolation`。演示：`python -m cropquarantine demo`。测试：`python -m pytest -q`。各入口接受 `--db` 和 `--file`；`report --db` 输出逐实体状态与来源。

病株点必须落在冻结田块内；`diagnose-import` 保存独立复核，确诊或驳回会改变下次隔离规划采用的阳性点。隔离范围按点到田块边界的最短距离传播，两个晚于阳性的阴性复查可解除，随后阳性复查会重新激活。转运申请会引用当时隔离版本；已出运批次因迟到阳性复核被撤销许可时形成 recall_required，`return-import` 仅在整批封签实物返回后关单。zone 与 movement_event 保留旧结论；`demo-decisions` 运行准运→出运→迟到阳性召回→整批退回的闭环。
