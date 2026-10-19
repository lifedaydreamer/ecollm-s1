# 标注与发布规范

样本单位是条款抽取、风险判断或文档对比较任务。每条记录保留来源文件、来源家族、许可、卖方视角、证据块与审核记录。

## 判断顺序

1. 确认输入证据完整、商品或条款对应关系明确。
2. 标记事实抽取结果；原始值与标准化值分开保存。
3. 对两份材料判定 consistent、different 或 insufficient。表述不同但含义一致时为 consistent。
4. difference 只表示条件变化；business_risk 必须说明相对哪条企业策略存在风险。
5. 信息缺失、解析失败、对应关系不确定或适用事实不足，标为 missing_info。
6. 证据引句必须逐字存在于指定块中。缺少证据的推断不能作为确定结论。

## 严重程度

- info：已发现差异或一般提示，没有证明损害或违背企业阈值。
- medium：存在影响业务判断的信息缺口，需要业务人员确认。
- high：违反已配置的预付款或账期策略，或存在明确算术差错，需要优先复核。

## 审核记录

程序生成记录的 review_status 为 pending。审核者核对全文、修改候选输出后，填写 reviewer、reviewed_at、review_notes，再设为 approved。验证和测试记录另填 second_reviewer，且必须是不同人员。专业法律解释还需相应专业人员复核。

禁止用模型名称冒充人工审核者。禁止批量将 pending 改为 approved 以绕过训练关口。

## 划分和规模

先按原始合同、模板和业务案例变体建立 source_family，再划分 train / validation / test。同一家族只能在一个分组中。

首轮正式发布目标是 3000 / 500 / 800 条任务。程序自建的 20 条候选都属于 tradepilot-template-v1，全部只作训练候选，不构成独立验证集。100 个 Agent 任务需要另建独立模板、预期状态与人工裁决。

发布命令：`python scripts/build_data.py --release reviewed.jsonl --output data/released`。发布器拒绝缺少审核记录或跨组来源家族的数据。
