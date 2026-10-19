# 自行运行与分享

本仓库有两份不同用途的交付：`showcase/` 是不需要后端的交互预览；Docker 工作台提供实际文件处理和审批。两者均不连接维护者的服务器。

## 无 GPU 默认模式

安装 Docker Desktop 或 Docker Engine + Compose v2、Python 3.11+ 后，在项目根目录运行：

```bash
python3 scripts/demo.py start
```

启动器生成仅属于本次部署的 `.env`，构建 API 和网页，等待健康检查通过后显示地址和密码。首次安装需要联网下载容器及依赖；后续不需模型网络访问。镜像和依赖缓存保存在使用者自己的 Docker 环境。

业务数据和 LangGraph checkpoint 保存在 `tradepilot-demo_documents` 数据卷。`stop` 不删除数据。保留 `.env` 以便再次登录。备份应在停止工作台后完整复制数据卷，并单独保管 `.env`；恢复时仍使用相同代码版本。这里没有自动备份服务。

若只想看演示，可以直接用浏览器打开下载包中的 `showcase/index.html`；不需要安装依赖。本页不提供 PDF 上传或真实审批。

<a id="model-mode"></a>
## 自己的本地模型模式

目标环境是 Linux x86_64、NVIDIA GPU 和可运行 CUDA 12.6 容器的驱动，安装 NVIDIA Container Toolkit。建议从 24GB 显存和至少 50GiB 可用磁盘开始验证；实际容量以输入长度和运行测量为准。当前工程推理验证使用 A100 80GB，不代表已完成 24GB 显卡验收。Mac / 无 NVIDIA GPU 的设备请使用规则模式。

### 下载并核验

下载工具不加载模型、不使用 GPU。只在希望存储模型的设备上执行：

```bash
python3 -m venv .download-venv
.download-venv/bin/pip install huggingface_hub
.download-venv/bin/python scripts/download_model.py \
  --output ./models/Qwen3-4B-Instruct-2507
```

无法连接 Hugging Face 时，可使用官方 ModelScope 发布：

```bash
.download-venv/bin/pip install modelscope
.download-venv/bin/python scripts/download_model.py \
  --source modelscope --output ./models/Qwen3-4B-Instruct-2507
```

已有权重可离线检查，下面的命令只需 Python 标准库：

```bash
python3 scripts/download_model.py --verify-only \
  --output ./models/Qwen3-4B-Instruct-2507
```

校验针对 `configs/model-manifest.json` 记录的 SHA-256，涵盖全部权重分片、索引和关键 tokenizer/config 文件。最初基座来自官方 ModelScope 发布，只记录了文件校验值，没有记录不可变上游 revision；这里如实保留此限制。Hugging Face 下载会额外记录解析得到的 commit revision。任何文件不一致都会报错，不将不同权重冒称同一基线。

### 启动

先通过 `nvidia-smi -L` 查看 UUID，并确保使用的是分配给自己的 GPU：

```bash
python3 scripts/demo.py start \
  --model-dir /absolute/path/Qwen3-4B-Instruct-2507 \
  --gpu GPU-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

启动器加载 `compose.model.yaml`，在使用者自己的容器网络中启动模型，API 只访问 `http://model:8102`。模型接口没有发布公网或宿主机端口。权重以只读方式挂载；没有权重时不会隐式下载。

GPU 防护连续检查指定设备，拒绝已有计算进程、显存不足、忙碌或磁盘不足的设备。不终止、重置或迁移其他进程。检查无法替代管理员或集群调度器的资源预约。模型容器不自动重启。

以后如有自己训练的 PEFT Adapter，追加 `--adapter /absolute/path/adapter`。目录需要包含 `adapter_config.json` 和对应权重，基座仍需单独准备。当前版本没有发布专业 Adapter。

启动配置保存在本机 `.runtime/demo-model.json`，以后 `start` 会复用模式。切回规则模式：

```bash
python3 scripts/demo.py start --rules-only
```

这会移除同一 Demo 项目中的模型容器，保留案例和本地权重。启动器只管理名为 `tradepilot-demo` 的容器，不操作其他 Docker 项目。请勿在同一 Docker 主机上用这个项目名运行多份副本。

### 复现边界

规则预览来自实际 Python 引擎：`python scripts/build_preview.py` 生成快照，CI 使用 `--check` 检查是否漂移。模型复现需要相同代码提交、校验通过的权重、相同输入与策略，并匹配运行版本；硬件和 90 秒生成时限仍可能影响输出。`configs/model-manifest.json` 记录了关键生成参数，完整已验证 GPU 环境快照见 `model-requirements.lock`。

GPU Docker 镜像固定 torch、transformers 和 JSON 约束库版本；目前 GPU 容器路径未在提供 Docker + NVIDIA 的独立环境中验收，不将原有裸机推理测试等同于该路径已验收。

## 发布静态展示入口

GitHub Pages 发布 `showcase/`，只托管 HTML、CSS、JavaScript 和三个虚构案例快照。它不会运行 Python 或大模型。仓库工作流 `.github/workflows/pages.yml` 已提供自动发布。

仓库管理员首次需要在 **Settings → Pages → Build and deployment → Source** 选择 **GitHub Actions**。之后推送主分支展示页变更或手动运行 **Browser showcase** 即可发布。

预期地址：`https://lifedaydreamer.github.io/ecollm-s1/`。Fork 后地址改为 `https://你的用户名.github.io/仓库名/`，相应修改 README 的展示链接即可。

也可直接分享仓库 ZIP。静态预览使用相对资源路径，解压后打开 `showcase/index.html` 即可交互；完整工作台仍需按 README 启动。

## 排错

| 现象 | 处理 |
| --- | --- |
| Docker 不存在或不能连接 | 启动 Docker Desktop；Linux 确认 Docker Engine 与 Compose v2 可用 |
| 3100 端口冲突 | 修改 `.env` 中 `TRADEPILOT_PORT`，重新运行 `start` |
| 浏览器提示登录 | 用户名 `tradepilot`，运行 `python scripts/demo.py password` 查看本机密码 |
| 网页只显示规则基线 | 默认行为；需要 GPU 时按上述命令启用模型模式 |
| GPU 启动被拒绝 | 查看日志，等待获配设备空闲；不要关闭他人任务或绕过防护 |
| 模型健康检查失败 | 检查只读权重目录权限、驱动、显存、磁盘、容器运行时和日志 |
| 扫描 PDF 没有正文 | 当前 OCR 尚未完成，先提供可提取文本版本或人工整理文本 |
| 重启后案例似乎丢失 | 确认仍是同一 Docker 主机、`tradepilot-demo` 项目和原数据卷 |

`requirements.lock` 是 API 的锁文件；Docker 默认工作台使用它。不同平台镜像构建仍由 CI 和本机安装结果验证。公开多人服务不在本次自部署 Demo 范围内，当前共享工作区账号仅供使用者自己的环境。
