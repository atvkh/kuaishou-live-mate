<div align="center">

<img src="logo.png" alt="旁白" width="120" height="120">

# 旁白

### 直播间 AI 互动助手（快手 + 抖音）

[![Version](https://img.shields.io/badge/version-1.1.1-blue.svg)](https://github.com/atvkh/kuaishou-live-mate/releases)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-lightgrey.svg)](https://github.com/atvkh/kuaishou-live-mate/releases)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10--3.12-yellow.svg)](https://www.python.org/)

实时监听直播间内容（弹幕 + 语音 + 画面），通过 LLM 生成拟人化评论自动发送，帮你热场。支持快手、抖音双平台一键切换。

[功能](#-功能) · [安装](#-安装) · [配置](#-配置) · [技术栈](#-技术栈) · [开发](#-开发)

</div>

---

## 📌 功能

| 模块 | 说明 |
|------|------|
| **双平台支持** | 快手 + 抖音，主面板一键切换，平台抽象层隔离差异 |
| **弹幕采集** | WebSocket 拦截 + Protobuf 解析，双方案兜底（Playwright 原生事件 + JS 注入 Hook） |
| **语音转录** | SenseVoiceSmall ONNX，中文准确率 90%+，5-15x 快于 Whisper，VAD 静音检测 + 自动过滤背景音乐 |
| **画面识别** | 进入直播间自动截图，视觉模型识别直播类型，注入 LLM 提示词 |
| **多模型回退** | 视觉模型优先级队列：`glm-4.6v-flash` → `glm-4.1v-thinking-flash` → `glm-4v-flash`，429 限流自动切换，思考模型输出过短自动跳过 |
| **拟人化评论** | 15% 水弹幕、随机长度分布、30% 语气词后缀、评论去重 |
| **自动点赞** | 进入直播间自动双击 video 元素触发点赞，默认开启，快手 5 秒/抖音 3 秒间隔，连续失败自动暂停 |
| **自动发送** | 抖音 fetch API 直接发送（无需 DOM 操作），快手 Playwright 定位输入框 |
| **悬浮舱** | 启动后自动切换迷你悬浮窗，实时显示状态 |
| **新手引导** | 首次启动配置向导 |
| **自动更新** | GitHub Releases 检查 + 静默升级 |

## 🚀 安装

### 普通用户（推荐）

1. 前往 [Releases](https://github.com/atvkh/kuaishou-live-mate/releases) 下载最新版安装包
2. 双击安装
3. 启动后按新手引导填写 API Key

> 安装包已内置 Python 运行时、依赖、SenseVoiceSmall 模型。首次启动会自动下载 Chromium。

### 开发者

```bash
git clone https://github.com/atvkh/kuaishou-live-mate.git
cd live-mate
pip install -r requirements.txt
playwright install chromium
python main.py
```

**前置要求**：Python 3.10-3.12（不支持 3.13）、[FFmpeg](https://ffmpeg.org/download.html) 加入 PATH

## ⚙️ 配置

首次启动自动从 `config.example.yaml` 复制 `config.yaml`，也可手动编辑：

```yaml
llm:
  provider: dashscope                          # 阿里云百炼
  api_key: '你的百炼API密钥'
  model: qwen3.7-plus-2026-05-26               # 推荐，更拟人

vision:
  provider: zhipu                              # 智谱AI（免费）
  api_key: '你的智谱API密钥'                    # 留空则复用 llm.api_key
  models:                                      # 多模型按优先级从上到下
    - glm-4.6v-flash
    - glm-4.1v-thinking-flash
    - glm-4v-flash

audio:
  whisper_model: sensevoice-small              # 推荐配置
  segment_length: 8
  vad_enabled: true                            # VAD 静音检测，减少乱码误识别
  vad_energy_threshold: 0.01                   # 能量阈值

sender:
  min_interval: 20                             # 不要低于 15，避免风控
  max_interval: 50
  max_length: 20

like:
  enabled: true                                # 进入直播间自动点赞
  interval: 5                                  # 快手默认 5 秒，抖音默认 3 秒
```

**API Key 获取**：[阿里云百炼](https://bailian.console.aliyun.com/) · [智谱 AI](https://open.bigmodel.cn/)

<details>
<summary>完整配置项</summary>

| 配置项 | 路径 | 默认值 | 说明 |
|--------|------|--------|------|
| 服务商 | llm.provider | dashscope | `dashscope` / `custom` |
| API密钥 | llm.api_key | - | LLM 密钥 |
| 模型 | llm.model | qwen-turbo | 推荐用 qwen3.7-plus |
| 接口地址 | llm.base_url | - | 仅 custom 需要 |
| 系统提示词 | llm.system_prompt | 见示例 | 决定评论风格 |
| 随机度 | llm.temperature | 0.9 | 越高越随机 |
| 字数 | llm.max_tokens | 30 | 评论 token 上限 |
| 视觉启用 | vision.enabled | true | 进入直播间截图识别 |
| 视觉密钥 | vision.api_key | - | 留空复用 LLM |
| 片段长度 | audio.segment_length | 8 | 每次识别音频秒数 |
| 弹幕采集 | danmu.enabled | true | - |
| 最大字数 | sender.max_length | 20 | - |

</details>

## 🧪 使用

1. 启动程序，首次运行弹出新手引导
2. 填写 API Key（百炼 + 智谱）
3. 点击启动 → 浏览器弹出快手/抖音
4. 扫码登录（自动记住）
5. 手动进入目标直播间
6. 程序自动工作：采集弹幕、转录语音、识别画面、生成并发送评论
7. 主窗口自动切换为悬浮舱

## 🛠️ 技术栈

| 类别 | 技术 |
|------|------|
| 语言 | Python 3.10+ |
| GUI | PyQt6（无边框 + 悬浮舱） |
| 浏览器自动化 | Playwright |
| 语音转录 | [funasr-onnx](https://github.com/manyeyes/funasr-onnx) (SenseVoiceSmall) |
| 视觉模型 | 智谱 GLM-4.6V-Flash 系列（免费，多模型回退） |
| LLM | OpenAI SDK 兼容接口（阿里云百炼 qwen 系列） |
| 协议 | Protobuf（快手 + 抖音 WebSocket 弹幕解析） |
| 打包 | PyInstaller (onedir) + Inno Setup |

## 📁 项目结构

```
kuaishou-live-mate/
├── main.py                  # 入口
├── config.example.yaml      # 配置模板
├── installer.iss            # Inno Setup 脚本
├── kuaishou-live-mate.spec  # PyInstaller 配置
├── tests/
│   └── functional_check.py  # 功能完整性检测（315项）
└── src/
    ├── core.py              # 核心引擎
    ├── gui.py               # GUI（悬浮舱+新手引导+平台切换）
    ├── audio.py             # 音频转录（SenseVoice + VAD）
    ├── danmu.py             # 弹幕采集
    ├── llm_client.py        # LLM 客户端
    ├── sender.py            # 评论发送（fetch API + DOM 双方案）
    ├── updater.py           # 自动更新
    ├── platforms/           # 平台抽象层
    │   ├── base.py          # 平台接口基类
    │   ├── kuaishou.py      # 快手实现
    │   └── douyin.py        # 抖音实现
    └── kuaishou_pb2.py      # Protobuf 定义
```

## 💻 开发

### 功能检测

UI 重构或代码改动后，运行检测脚本验证功能完整性：

```bash
python tests/functional_check.py
```

覆盖 17 大类 315 项：环境依赖、模块导入、版本一致性、配置系统、GUI 控件、信号槽、视觉模型回退、拟人化评论、切换直播间修复、平台抽象层等。

### 打包

```bash
python -m PyInstaller kuaishou-live-mate.spec --clean
iscc installer.iss
```

> 安装包约 1GB，超过 GitHub 100MB 单文件限制，通过 Releases 发布。

## ⚠️ 注意

- 评论间隔建议 ≥ 20 秒，过短可能被风控
- headless 模式不支持音频，程序以有头浏览器运行
- 首次启动较慢（模型加载约 240MB）
- Python 3.13 不兼容（funasr-onnx 未适配）
- 本项目仅供学习交流，请勿用于违规用途

## 📚 参考

- [kuaishou_websocket](https://github.com/Superheroff/kuaishou_websocket) - 快手弹幕 WebSocket + Protobuf
- [BarrageGrab](https://gitee.com/ocean_T/BarrageGrab) - 多平台弹幕采集（C#）
- [SenseVoice](https://github.com/FunAudioLLM/SenseVoice) - 语音识别模型
- [funasr-onnx](https://github.com/manyeyes/funasr-onnx) - FunASR ONNX 推理引擎

## 📄 License

[MIT](LICENSE) © 2026 [atvkh](https://github.com/atvkh)
