# 旁白 - 快手直播间AI互动助手

用你自己的快手账号，实时监听朋友直播间内容（弹幕 + 主播语音 + 直播画面），通过 LLM 生成自然口语化评论，自动发送到直播间热场。

> **当前版本**：v1.0.8 | **发布者**：atvkh | **License**：MIT

## 功能特性

- **弹幕采集**：WebSocket 拦截 + Protobuf 解析，实时捕获直播间弹幕（双方案：Playwright 原生事件 + JS 注入 Hook，互为兜底）
- **语音转录**：FFmpeg 提取直播流音频 + **SenseVoiceSmall ONNX** 实时转文字（阿里通义实验室 FunASR 系列，中文准确率 90%+，5-15x 快于 Whisper，自带音频事件检测过滤背景音乐）
- **直播画面识别**：进入直播间时自动截图，调用视觉模型识别直播类型和内容，注入 LLM 提示词
- **多模型自动回退**：视觉模型支持多模型优先级队列（`glm-4.6v-flash` → `glm-4.1v-thinking-flash` → `glm-4v-flash`），429 限流时自动切换
- **拟人化评论生成**：15% 概率发水弹幕、随机评论长度分布、30% 概率加语气词后缀、评论去重
- **评论自动发送**：Playwright 自动化定位输入框填入文本并发送
- **登录态管理**：扫码登录后自动保存 Cookie，下次启动免登录
- **自动更新**：启动时检查 GitHub Releases 新版本，支持静默升级
- **桌面悬浮舱**：启动后自动切换为迷你悬浮窗口，实时显示状态，不占屏幕空间
- **新手引导**：首次启动自动弹出配置向导，引导填写 API Key
- **运行日志查看器**：独立日志窗口，支持置顶和智能滚动
- **无边框界面**：自定义标题栏 + 半透明背景 + 阴影，现代化 UI 设计

## 系统架构

```
用户点击"启动"
    │
    ▼
Playwright 打开快手 → 扫码登录 → 用户手动进入直播间
    │
    ├── 弹幕通道: WebSocket拦截 → Protobuf解析(payloadType=310)
    ├── 语音通道: 直播流 → FFmpeg提音频 → SenseVoiceSmall转文字
    ├── 视觉通道: 截图直播画面 → 视觉模型识别直播类型
    └── 评论循环: 弹幕+转录+画面 → LLM → 自动发送
```

## 安装

### 方式一：下载安装包（推荐）

前往 [Releases 页面](https://github.com/atvkh/kuaishou-live-mate/releases) 下载最新版安装包，双击安装即可。

> 安装包已内置 Python 运行时、所有依赖、SenseVoiceSmall ONNX 模型，无需额外配置。首次运行会自动下载 Playwright Chromium 浏览器。

### 方式二：源码运行（开发者）

#### 前置依赖

- **Python 3.10-3.12**（暂不支持 3.13，部分依赖未适配）
- [FFmpeg](https://ffmpeg.org/download.html)（加入系统 PATH）
- [阿里云百炼](https://bailian.console.aliyun.com/) API Key（LLM 用）
- [智谱 AI](https://open.bigmodel.cn/) API Key（视觉模型用，免费）

#### 安装步骤

```bash
git clone https://github.com/atvkh/kuaishou-live-mate.git
cd kuaishou-live-mate
pip install -r requirements.txt
playwright install chromium
```

### 配置

1. 复制示例配置文件：
   ```bash
   cp config.example.yaml config.yaml
   ```
2. 编辑 `config.yaml`，填写 API Key：
   ```yaml
   llm:
     api_key: '你的阿里云百炼API密钥'
   vision:
     api_key: '你的智谱API密钥'   # 留空则复用 llm.api_key
     models:                       # 多模型按优先级从上到下
       - glm-4.6v-flash
       - glm-4.1v-thinking-flash
       - glm-4v-flash
   ```

> 首次启动如果 `config.yaml` 不存在，程序会自动从 `config.example.yaml` 复制。首次运行还会弹出新手引导。

## 使用方法

1. 启动程序：`python main.py`
2. 首次启动弹出新手引导，按提示填写 API Key
3. 点击 **启动**，浏览器自动弹出快手直播首页
4. 扫码登录（登录后自动记住）
5. 在浏览器中手动进入目标直播间
6. 程序自动开始工作：采集弹幕、转录语音、识别画面、生成并发送评论
7. 启动后主窗口自动切换为桌面悬浮舱，点击可展开/收起

## 配置说明

### LLM 配置

| 配置项 | 路径 | 默认值 | 说明 |
|--------|------|--------|------|
| 服务商 | llm.provider | dashscope | `dashscope`(百炼) 或 `custom`(自定义) |
| API密钥 | llm.api_key | - | LLM API 密钥 |
| 模型 | llm.model | qwen-turbo | 推荐用 qwen3.7-plus 效果更拟人 |
| 接口地址 | llm.base_url | - | 仅 custom 模式需要 |
| 系统提示词 | llm.system_prompt | 见示例 | 决定评论风格 |
| 随机度 | llm.temperature | 0.9 | 越高越随机 |
| 字数 | llm.max_tokens | 30 | 评论最大 token 数 |

### 视觉识别配置

| 配置项 | 路径 | 默认值 | 说明 |
|--------|------|--------|------|
| 启用 | vision.enabled | true | 进入直播间时截图识别 |
| 服务商 | vision.provider | zhipu | `zhipu`(智谱) / `dashscope` / `custom` |
| API密钥 | vision.api_key | - | 留空则复用 LLM 密钥 |
| 模型列表 | vision.models | 见示例 | **多行文本，每行一个模型名，按优先级从上到下** |

### 语音识别配置

| 配置项 | 路径 | 默认值 | 说明 |
|--------|------|--------|------|
| 识别模型 | audio.whisper_model | sensevoice-small | `sensevoice-small`(推荐) / tiny / base / small / medium / large |
| 片段长度 | audio.segment_length | 8 | 每次识别音频长度（秒） |
| 弹幕采集 | danmu.enabled | true | 是否启用弹幕采集 |

### 评论发送配置

| 配置项 | 路径 | 默认值 | 说明 |
|--------|------|--------|------|
| 最小间隔 | sender.min_interval | 20 | 评论最小间隔（秒），不要低于 15 |
| 最大间隔 | sender.max_interval | 50 | 评论最大间隔（秒） |
| 最大字数 | sender.max_length | 20 | 评论最大字数 |

## 技术栈

- **Python 3.10+** / PyQt6 / Playwright / OpenAI SDK / Protobuf
- **语音转录**：[funasr-onnx](https://github.com/manyeyes/funasr-onnx) (SenseVoiceSmall)
- **视觉模型**：智谱 GLM-4.6V-Flash / GLM-4.1V-Thinking-Flash / GLM-4V-Flash（免费，多模型自动回退）
- **打包**：PyInstaller (onedir) + Inno Setup

## 文件结构

```
kuaishou-live-mate/
├── main.py                      # 程序入口
├── config.example.yaml          # 示例配置（提交到仓库）
├── config.yaml                  # 用户配置（gitignore，含密钥）
├── cookies.json                 # 自动保存的登录Cookie（gitignore）
├── requirements.txt             # Python依赖
├── installer.iss                # Inno Setup安装包脚本
├── kuaishou-live-mate.spec      # PyInstaller打包配置
├── version_info.txt             # exe文件版本信息
├── app.ico                      # 应用图标
├── LICENSE                      # MIT许可证
├── README.md                    # 本文档
├── tests/
│   └── functional_check.py      # 功能完整性检测脚本（16大类240项）
└── src/
    ├── __init__.py              # 版本号、APP_DIR、DATA_DIR定义
    ├── core.py                  # 核心引擎，协调所有模块 + 扫码登录 + 截图识别
    ├── audio.py                 # 音频转录（FFmpeg + SenseVoiceSmall）
    ├── danmu.py                 # 弹幕采集（WebSocket拦截 + Protobuf解析）
    ├── kuaishou_pb2.py          # 快手WebSocket Protobuf定义
    ├── llm_client.py            # LLM客户端（百炼/自定义API，支持热更新）
    ├── sender.py                # 评论发送（Playwright自动化）
    ├── gui.py                   # PyQt6 GUI界面（无边框+悬浮舱+新手引导）
    └── updater.py               # 自动更新（GitHub Releases检查/下载/静默安装）
```

## 注意事项

- **评论发送间隔不要太短**，建议最小 20 秒，频繁发送可能被风控
- **headless 模式不支持音频**，程序以有头浏览器运行
- **首次启动较慢**，SenseVoiceSmall 模型需要加载（约 240MB）
- **Python 3.13 不兼容**：funasr-onnx 等依赖暂未适配，请使用 Python 3.10-3.12
- 本项目仅供学习交流，请勿用于违规用途

## 参考

- [kuaishou_websocket](https://github.com/Superheroff/kuaishou_websocket) - 快手弹幕 WebSocket + Protobuf 采集
- [BarrageGrab](https://gitee.com/ocean_T/BarrageGrab) - 多平台弹幕采集（C#）
- [SenseVoice](https://github.com/FunAudioLLM/SenseVoice) - 语音识别模型
- [funasr-onnx](https://github.com/manyeyes/funasr-onnx) - FunASR ONNX 推理引擎

## License

MIT © 2026 atvkh
