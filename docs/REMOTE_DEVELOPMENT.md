# TradePilot 贸航 AI

跨境 B2B 多文档审查工作台与独立专业模型接口。当前交付为可运行原型，已实现业务案例、解析与证据、确定性审查、人工校对、版本复查、审批归档和报告导出。正式微调模型与竞赛性能结论需要后续审核数据和独立评测。

## 已部署的远程目录

`mya-server:/home/mya/workspace/ecollm-s1`

应用与依赖位于项目隔离目录；模型只存储于远程 `/data/yzh/tradepilot-models`。不更改系统包，不停止其他任务，不将大模型传回本机。

## 访问工作台

在自己的电脑执行：

```sh
ssh -N -L 18310:127.0.0.1:3100 mya-server
```

然后打开 `http://127.0.0.1:18310`。登录用户名是 `tradepilot`，密码为服务器 `.runtime/env.json` 内的 `TRADEPILOT_TOKEN`。凭据仅保存在服务器，未提交到仓库。API 与网页只监听远程回环地址，网页和代理也要求认证，防止共享主机的其他用户通过网页代理访问案例。演示包含正常、条件变化、信息不足三种虚构材料。

## 远程启动与状态

```sh
cd /home/mya/workspace/ecollm-s1
.venv/bin/python scripts/services.py status api
.venv/bin/python scripts/services.py status web
.venv/bin/python scripts/services.py start api
.venv/bin/python scripts/services.py start web
```

访问密钥在 `.runtime/env.json`，仅服务器本项目使用，禁止提交到 GitHub。网页代理在服务端注入 API 密钥。

新环境安装：Python 3.12 下 `python -m venv .venv`，然后 `.venv/bin/pip install -e '.[test]'`。Node 22 下在 web 目录执行 `npm ci && npm run build`。服务管理器使用本项目 `.runtime/node/bin/node`；若使用系统 Node，按本机路径调整该启动项。

## 独立模型 API

`POST /v1/analyze` 接收 `task: extract|review|compare`、带 ID 和证据块的 documents、policy，返回统一 AnalyzeResponse。客户端执行：

```sh
TRADEPILOT_MODEL_TOKEN=... tradepilot input.json --endpoint http://127.0.0.1:8102
```

模型服务只加载本地权重，禁止启动时隐式联网下载。启动必须通过 `scripts/services.py start model --gpu GPU-完整UUID`，资源检查至少采样三次，任何计算进程存在时拒绝启动，显存与磁盘不足时同样拒绝，不自动换卡。

推理原型使用 Transformers；vLLM 的高吞吐部署尚待单独验收。业务 API 默认使用规则基线，模型 URL 在 `.runtime/env.json` 配置后需重启本项目 API。所有覆盖限制写入报告，归档需人工明确确认。

## 测试与数据

```sh
.venv/bin/python -m pytest -q
cd web && npm run typecheck && npm run build
```

```sh
.venv/bin/python scripts/build_data.py --count 20
.venv/bin/python scripts/build_data.py --release reviewed.jsonl --output data/released
```

生成数据属于同一模板家族，不用于独立评测，不能自动当作人工金标准。详见 [标注规范](docs/ANNOTATION.md)。正式训练命令为 `python scripts/train.py --gpu GPU-完整UUID`，缺少审核发布清单或未达到训练样本门槛时拒绝执行。

正式训练还需在单独训练环境安装 LLaMA-Factory 与相应量化依赖，并先停止本项目推理服务，使训练与推理错峰。当前交付没有执行这一步，也没有正式 Adapter。

## 其他部署

Compose 的当前自行运行入口见 [自行运行指南](SELF_HOSTING.md)，默认使用 SQLite。开发主机未安装 Docker。原型工作流 checkpoint 使用本地 SQLite；单进程后端将业务变更串行化。迁移脚本与现有自动初始化互斥：新库先执行 Alembic，再启动应用；已有原型库使用 `alembic stamp 0001` 前必须先核对表结构并备份。

完整能力与未完成事项请以 [实施状态](docs/STATUS.md) 为准。尚未完成的专业数据复核、正式 Adapter、100 任务基准、用户试用与竞赛视频均不冒称已经完成。
