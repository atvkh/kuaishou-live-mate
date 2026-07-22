# 直播伴侣 - 快手直播间AI互动助手

用你自己的快手账号，实时监听朋友直播间内容（弹幕 + 主播语音），通过 LLM 生成互动评论，自动发送到直播间热场。

## 功能

- **弹幕采集**：WebSocket 拦截 + Protobuf 解析，实时捕获直播间弹幕
- **语音转录**：FFmpeg 提取直播流音频 + faster-whisper 实时转文字
- **说话人分离**：MFCC 特征 + KMeans 聚类，区分连麦 PK 场景的不同说话人
- **AI 评论生成**：根据弹幕和语音转录内容，通过 LLM 生成自然、口语化的互动评论
- **评论自动发送**：Playwright 自动化，定位输入框填入文本并发送
- **登录态管理**：扫码登录后自动保存 Cookie，下次启动免登录
- **GUI 界面**：PyQt6 浅色主题，弹幕 / 语音转录 / AI 评论 / 日志四个标签页

## 系统架构

```
用户点击"启动"
    │
    ▼
Playwright 打开快手 → 扫码登录 → 用户手动进入直播间
    │
    ├── 弹幕通道: WebSocket拦截 → Protobuf解析(payloadType=310)
    ├── 语音通道: 直播流 → FFmpeg提音频 → Whisper转文字
    └── 评论循环: 弹幕+转录 → LLM → 自动发送
```

## 安装

### 前置依赖

- Python 3.10+
- FFmpeg（需加入系统 PATH，[下载地址](https://ffmpeg.org/download.html)）
- [阿里云百炼](https://bailian.console.aliyun.com/) API Key（或其他 OpenAI 兼容 API）

### 安装步骤

```bash
git clone https://github.com/你的用户名/直播伴侣.git
cd 直播伴侣
pip install -r requirements.txt
playwright install chromium
```

### 配置

1. 复制示例配置文件：
   ```bash
   cp config.example.yaml config.yaml
   ```
2. 编辑 `config.yaml`，填写你的 API Key：
   ```yaml
   llm:
     api_key: '你的API密钥'
   ```

> 首次启动如果 `config.yaml` 不存在，程序会自动从 `config.example.yaml` 复制。

## 使用方法

1. 启动程序：
   ```bash
   python main.py
   ```
2. 点击 **设置**，确认 API Key 等配置正确
3. 点击 **启动**
4. 浏览器自动弹出快手直播首页
5. 如果未登录，扫码登录（登录后自动记住）
6. 在浏览器中手动进入目标直播间
7. 程序自动开始工作：采集弹幕、转录语音、生成并发送评论

## 配置说明

| 配置项 | 路径 | 默认值 | 说明 |
|--------|------|--------|------|
| 服务商 | llm.provider | dashscope | `dashscope`(百炼) 或 `custom`(自定义) |
| API密钥 | llm.api_key | - | LLM API 密钥 |
| 模型 | llm.model | qwen-turbo | 百炼可用 qwen-turbo/plus/max |
| 随机度 | llm.temperature | 0.9 | 越高越随机 |
| Whisper模型 | audio.whisper_model | small | tiny/base/small/medium/large |
| 音频片段 | audio.segment_length | 5 | 每次识别音频长度（秒） |
| 说话人分离 | audio.enable_diarization | false | 连麦PK场景建议开启 |
| 最小间隔 | sender.min_interval | 20 | 评论最小间隔（秒），建议不低于15 |
| 最大间隔 | sender.max_interval | 50 | 评论最大间隔（秒） |
| 评论字数 | sender.max_length | 20 | 评论最大字数 |

## 技术栈

- **Python 3.13** / PyQt6 / Playwright / faster-whisper / OpenAI SDK / Protobuf

## 文件结构

```
直播伴侣/
├── main.py              # 程序入口
├── config.example.yaml  # 示例配置（提交到仓库）
├── config.yaml          # 用户配置（gitignore，含密钥）
├── cookies.json         # 自动保存的登录Cookie（gitignore）
├── requirements.txt     # Python依赖
├── LICENSE              # MIT许可证
└── src/
    ├── core.py           # 核心引擎，协调所有模块
    ├── audio.py          # 音频转录（FFmpeg + faster-whisper）
    ├── danmu.py          # 弹幕采集（WebSocket拦截 + Protobuf解析）
    ├── kuaishou_pb2.py   # 快手WebSocket Protobuf定义
    ├── llm_client.py     # LLM客户端（百炼/自定义API）
    ├── sender.py         # 评论发送（Playwright自动化）
    └── gui.py            # PyQt6 GUI界面
```

## 注意事项

- **评论发送间隔不要太短**，建议最小 20 秒，频繁发送可能被风控
- **headless 模式不支持音频**，程序以有头浏览器运行
- **首次启动较慢**，Whisper 模型需要下载（small 约 500MB）
- 本项目仅供学习交流，请勿用于违规用途

## 参考

- [kuaishou_websocket](https://github.com/Superheroff/kuaishou_websocket) - 快手弹幕 WebSocket + Protobuf 采集
- [BarrageGrab](https://gitee.com/ocean_T/BarrageGrab) - 多平台弹幕采集（C#）

## License

MIT
