# 面向参赛的专业模型训练路线

## 目前最需要解决的问题

智能体已经具有跨文档、企业策略和人工审批等场景功能，但语义专业能力目前主要来自原始通用模型。尚未证明它能稳定理解自然语言付款触发条件、责任例外和不同措辞之间的关系，也没有专业风险金标准上的增益结论。

训练应先针对能够测量、已有可靠标签的任务，再扩展到外贸风险判断。OCR 错字、知识来源不完整、权限与队列、真实用户收益仍需独立改进，微调不能替代这些工作。

## 第一阶段：CUAD 商业合同条款抽取试训

使用 The Atticus Project 发布的 CUAD v1。其 510 份商业合同具有专家监督的条款标注，许可为 CC BY 4.0。它并非外贸专用数据集；本实验不把其标签转换成未经复核的风险等级。

本轮选择九类：责任上限、无限责任、违约金、保证期限、保险、审计权、任意解除、准据法、最低承诺。目标是从给定英文片段中找出相关原文；“片段未发现”不表示整份合同缺少该条款。

- 上游版本：`67faa0e6023b04fcaae6cc09497ab00e5d63a2a2`。
- 数据包 Git Blob：`1ae94ff0a9b70b2e3b9b8d215737c8bfae460ddc`。
- 数据包 SHA-256：`f8161d18bea4e9c05e78fa6dda61c19c846fb8087ea969c172753bc2f45b999a`。
- 训练 / 验证 / 测试：**711 / 54 / 72** 条片段级任务；不是 837 份不同合同。
- 使用原始专家引句，逐项校验字符偏移，不新增卖方/买方角色和风险标签。
- 固定字符窗口，不按答案位置居中；移除切断标注引句的窗口，因此结果仅适用于这个过滤子集。
- 保留官方测试合同；移除训练中与测试合同具有相同发行主体前缀的材料，验证集也按主体分组。
- 跨组移除完全相同的标准化片段；近重复模板、发行主体别名和预训练污染仍不能完全排除。

发布来源与标注属性写入专用清单，不将程序生成候选批量改为人工 approved。原先正式多任务数据发布的审核门槛继续保留；本轮是单独记录的公开专家标注试训。

## 训练与公平对照

基座沿用本地 `Qwen3-4B-Instruct-2507`，启动前核对原有模型文件哈希。本轮使用 BF16 LoRA：rank 16、alpha 32、dropout 0.05、q/v 投影层、学习率 1e-4、一个 epoch、batch 2、梯度累积 2、种子 42。不安装或修改系统训练环境；复用隔离模型环境中已有的 Transformers 与 PEFT。

只对 assistant 回答计算损失。超过长度直接拒绝，不静默截断引句。单 GPU 显存上限设为设备的 70%，并记录实际峰值。

基座与 Adapter 使用相同提示词、片段、JSON 输出约束及贪心解码。约束后的 JSON 合法率不冒充原始生成合法率。第一轮先比较验证集；证据 token F1 提升至少 2 个百分点且可验证引用比例无明显退化时，才运行已冻结测试集。此门槛只是决定是否继续实验，不代表达到正式参赛验收标准。

报告指标为条款存在判断 Macro-F1、证据 token F1、原文引句校验率和完整引句集合匹配率。它们不是“外贸风险 Macro-F1”。首轮只有一个随机种子和较小公开数据子集，不能作为最终独立效果结论。

## 第二阶段：TradePilot 外贸专项数据

公开商业合同数据可以训练条款定位，但不能充分覆盖产品核心场景。后续专项数据应包括：

| 任务 | 样本内容 | 标签依据 |
|---|---|---|
| 付款条件抽取 | 分散的预付款、尾款、账期、付款触发事件 | 明确原文与标准化规范 |
| 跨文档比较 | 报价与合同的实质变化、同义改写、信息不足 | 对应条款双方证据及专业复核 |
| 策略风险 | 相同条款配不同企业策略，包含合理例外 | 明确策略版本，不凭条款单独判高风险 |
| 责任与验收 | 上限、例外、索赔期限、解除及关联章节 | 国际商务/合同知识复核，保留分歧裁决 |
| 正常与困难负例 | 措辞变化但条件一致、表面数字相同但触发事件不同 | 防止只学关键词或把所有变化当风险 |

先制作一批规模可控、覆盖错误类型的审核集，再根据学习曲线扩充；不把凑满某个条数当成质量保证。合成材料可以作为候选，但新标签必须复核。来源合同、同一模板和业务变体在划分前分组。

ContractNLI 可用于研究合同推理，但其原任务是 NDA 的假设蕴含判断，不能机械映射为报价/合同的三分类。若采用，应保持原任务语义或另行专业标注。贸易术语规则还须遵守文本使用许可，不直接抓取受限规则全文训练。

## 方向二的交付条件

试训如果有效，可以继续形成“英文国际商务合同条款识别与证据抽取”模型作品；现阶段不宣称是成熟外贸合规模型。正式作品需要：

1. Adapter、基座身份与哈希、推理入口、依赖和训练配置。
2. 数据卡、来源许可、转换方法、划分与去重记录。
3. 优化提示词基线与微调模型公平对照，进一步进行三随机种子及错误分析。
4. 独立外贸任务和用户试用，验证公开商业合同能力能否迁移。
5. 模型卡中如实记录适用范围、未改善和退化的类别。

只有通过验证后才考虑接入智能体默认业务路径；先提供独立模型入口。这份 Adapter 学习的是独立 clause 输入/输出格式，不能直接用 `demo.py --adapter` 替换现有 extract/review/compare 服务；还需专门的工具路由和工作流验收。方向一与方向二的最终报名和成果复用方式，以赛事正式细则为准。

## 服务器执行原则

不在普通电脑下载基座或训练。GPU 0、1、3 有其他计算任务时不使用。若需要本项目当前使用的设备，只暂停经 PID、启动时间、用户、目录和 GPU 参数核实的本项目推理管理进程；释放后仍须通过连续三次空闲检查。存在任何计算进程则拒绝训练，不驱逐任务，不自动换卡。试训调度在 finally 中请求恢复原推理服务，恢复是否成功仍需独立核验。

## 可复现入口

- `ml/prepare_cuad.py`：来源校验、固定窗口、分组与数据清单。
- `ml/train_clause_pilot.py --prepare-only`：CPU 数据、长度、基座哈希检查。
- `ml/train_clause_pilot.py`：经 GPU 资源检查后的独立 LoRA 试训及对照评测。
- `ml/predict_clause.py`：不启动业务平台的基座/Adapter 推理。
- `ml/run_remote_pilot.py`：仅管理已核实属于本项目的模型服务。

来源：[CUAD 官方说明](https://www.atticusprojectai.org/cuad/)、[官方代码与数据](https://github.com/The-Atticus-Project/cuad)、[CUAD 论文](https://arxiv.org/abs/2103.06268)、[ContractNLI 原任务说明](https://stanfordnlp.github.io/contract-nli/)。

### 独立推理示例

推荐从最新源码安装已发布 Adapter：

```bash
python scripts/download_adapter.py --output adapters/cuad-pilot-v1
python scripts/download_adapter.py --output adapters/cuad-pilot-v1 --verify-only
```

已有 ZIP 可使用 `--bundle /path/to/TradePilot-CUAD-Pilot-v0.1.0.zip`，执行相同的完整包与文件哈希校验。安装保留模型许可和数据归属，拒绝覆盖已有目录；不需要 Torch、GPU 或基座。使用最新源码加安装后的权重，可避免误用发布页面关联旧应用基线的自动 Source code 压缩包。原始训练快照及冻结实验结果继续保持原版本。

在已经获配且无人使用的 GPU 上，先通过资源检查，再运行：

```bash
python scripts/gpu_guard.py --gpu GPU-替换为完整UUID -- \
  python ml/predict_clause.py \
    --model /path/to/Qwen3-4B-Instruct-2507 \
    --adapter /path/to/experiment/adapter \
    --input data/examples/clause-request.json
```

省略 `--adapter` 就是同一任务的原始基座入口。该入口在加载模型前自动校验全部已登记基座文件、已发布 Adapter 权重及其关键配置；不匹配时停止。其他新训练 Adapter 需先单独发布身份清单与验收，不能冒用本实验清单。该示例是自写虚构文本，不属于训练或评测金标准。不要将示例 UUID 直接复制为真实设备参数。

### 独立训练环境

在服务器创建独立 Python 3.12 环境，先按官方 CUDA 兼容说明安装 `torch==2.9.1`（本轮为 cu126），再安装 `ml/requirements-pilot.txt`。本轮直接复用原有隔离环境，没有改动系统依赖。完整原环境快照见 `model-requirements.lock`；硬件与驱动仍须单独核验兼容性。

### 复现数据和单卡实验

以下命令在训练服务器的项目根目录执行，示例路径和 GPU UUID 必须替换：

```bash
mkdir -p data/source
curl -Lf -o data/source/cuad-data.zip \
  https://raw.githubusercontent.com/The-Atticus-Project/cuad/67faa0e6023b04fcaae6cc09497ab00e5d63a2a2/data.zip
python ml/prepare_cuad.py --archive data/source/cuad-data.zip --output data/cuad-pilot-v1
python ml/train_clause_pilot.py --prepare-only \
  --model /path/to/Qwen3-4B-Instruct-2507 --data data/cuad-pilot-v1 \
  --config configs/cuad-pilot.json --output experiments/new-cuad-pilot
python scripts/gpu_guard.py --gpu GPU-替换为完整UUID --min-free-mib 40000 -- \
  python ml/train_clause_pilot.py \
    --model /path/to/Qwen3-4B-Instruct-2507 --data data/cuad-pilot-v1 \
    --config configs/cuad-pilot.json --output experiments/new-cuad-pilot
```

准备检查不会创建实验输出目录；正式执行拒绝覆盖已有实验。输出包含 Adapter、数据/代码/基座身份、训练日志、基座与微调预测和评测摘要。未通过验证增益门槛时，测试集保持未评测状态。

数据准备也拒绝覆盖已有非空输出目录。已有冻结切片时直接使用并校验；需要重新生成时选择新的数据版本目录，避免改写封存划分。
