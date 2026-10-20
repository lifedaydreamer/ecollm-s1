# CUAD V2 实验协议

V2 在 V1 的九类公开合同条款抽取任务上扩大专家标注数据，并增加较强提示词基线、困难负例、三随机种子与未使用来源家族确认集。训练与业务规则优化分别计分；结果尚未冻结前，不将实验配置当作模型能力提升。

## 数据与对照

- 训练：1,921 条任务，只使用 V1 训练来源家族；保留原公开专家引句，不用生成式模型改写标签。
- 验证：原 V1 的 54 条，用于候选配置及种子选择。
- 新确认集：106 条，62 个此前全部 V1 分区均未使用的来源家族；去除已用上下文的完全重复项。配置选择前不评测该集合。
- 回归：原 72 条测试，只作退化检查，不用于选择。
- 过滤片段长度、家族标识与完全去重不能完全消除近似重复、发行主体别名或预训练污染；该实验不证明完整合同风险识别能力。

在同样的结构化输出约束、greedy 解码、每批 4 条、2,048 tokens 上下文和最多 768 tokens 输出下，比较原基座、V1、V2；基座与 V1 分别测试原提示词及加入原 CUAD 类别定义的提示词。只有同提示词对照才能用于解释训练收益。

## 冻结的训练与选择规则

候选 A：BF16 LoRA，q/v 层，rank 32、alpha 64、dropout 0.05，学习率 5e-5，2 轮；batch 4、累计 2，seed 42。候选 A 不达标时，才运行候选 B：rank 16、alpha 32、学习率 1e-4、1 轮，其余相同。

V2 验证证据 token F1 必须比原基座及 V1 的最强验证基线至少高 **2 个百分点**，回答内全部引句可匹配率不能退化超过 2 个百分点。两候选都未通过则保留确认集封存，并如实报告未取得验证增益。

通过门槛后，以获胜配置从原基座分别训练 seed 43、44；仅按验证结果选默认种子。记录选择时间和确认集哈希后，再执行新来源确认与旧测试回归。报告全部三种子均值与样本标准差、按来源家族的配对 bootstrap 区间及退化案例。

训练脚本使用标准 Transformers / PEFT BF16 LoRA；本轮并非原规划中的 NF4 QLoRA，正式外贸多任务数据也未完成。

## 可复现入口

首先按 V1 [训练报告](TRAINING_REPORT.md) 取得带原始许可的固定版本 CUAD 源包，并用原 `ml/prepare_cuad.py` 复现 V1 711/54/72 分区，再执行：

```bash
python ml/prepare_clause_v2.py --archive data/source/CUAD_v1.zip --pilot data/cuad-pilot-v1 --output data/cuad-v2
python scripts/gpu_guard.py --gpu GPU-替换为获配设备的完整UUID -- \
  python ml/run_clause_suite.py --model /absolute/base/model --data data/cuad-v2 \
  --output experiments/v2-suite --config configs/cuad-v2.json --old-adapter adapters/cuad-pilot-v1
```

输出目录必须为空。脚本先冻结计划、数据哈希及候选配置，实际训练记录基座和源码哈希。原基座与 V1 Adapter 均核验身份；超长证据拒绝静默截断。完成后使用 `ml/summarize_clause_suite.py` 复核预测与按家族配对统计。

## 本次共享 GPU 的额外限制

默认 `scripts/gpu_guard.py` 继续拒绝已有计算进程。本次仅因设备所有者明确授权 GPU 2 共享及 24GiB 上限，才使用独立 `scripts/cooperative_gpu_guard.py`。

共享入口需准确 GPU UUID、明确现有进程或显式快照授权、连续三次现有进程稳定检查（默认还要求低利用率；已获准计算共享时可显式追加 `--allow-busy-shared`）；Torch allocator 上限 22GiB，为 CUDA 上下文等保留余量。监测新任务合计显存不得超过 24GiB，设备空闲显存至少保留 16GiB。守护失败只停止自己创建且身份核验通过的进程组，从不终止 NVIDIA 查询发现的其他进程。

共享模式无法预约集群资源；管理员或调度器的分配优先。`ml/run_remote_pilot.py` 是本项目开发服务的专用暂停/恢复工具，仅允许停止身份、启动时间、工作目录和 GPU 均核验一致的本项目模型管理进程；不要用于管理其他人的服务。

已完成验证基线因驱动故障中断后，可在新的输出目录使用 `--baseline-suite /path/to/prior/suite`：校验数据清单、候选配置、样本 ID、解码策略，并从预测重算全部分数，生成复用文件哈希记录；不复用或读取确认集结果。
