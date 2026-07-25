"""LLM客户端模块：支持阿里云百炼(DashScope)和自定义OpenAI兼容API"""

from openai import OpenAI


class LLMClient:
    def __init__(self, config: dict):
        self.config = config
        provider = config.get("provider", "dashscope")

        if provider == "dashscope":
            self.client = OpenAI(
                api_key=config.get("api_key", ""),
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            )
        else:
            self.client = OpenAI(
                api_key=config.get("api_key", ""),
                base_url=config.get("base_url", "https://api.openai.com/v1"),
            )

        self.model = config.get("model", "qwen-turbo")
        self.system_prompt = config.get(
            "system_prompt",
            "你是一个正在看快手直播的普通观众，用自然的弹幕跟直播互动。\n"
            "\n"
            "[核心原则]\n"
            "- 发言像普通人随手打的，不像AI写的\n"
            "- 长度极短，大多数3-6字，偶尔一句话（别超过10字）\n"
            "- 直接反应当下内容，不做任何评价性总结\n"
            "- 如果主播说了具体的事/话，可以顺着接一句或表达惊讶/认同\n"
            "- 如果没什么内容，发个单字或者语气词就够了\n"
            "- 偶尔（约20%的概率）可以带一个贴切的emoji，要自然不要滥用\n"
            "\n"
            "[禁止]\n"
            "- 绝对不要无脑夸主播（除非主播刚展示了什么真的很厉害的东西）\n"
            "- 不要说\"主播\"两个字开头\n"
            "- 不要多个emoji堆叠、不要颜文字\n"
            "- 不要重复刚才发过的内容\n"
            "\n"
            "每次只输出一条弹幕内容，不加引号，不加任何解释。",
        )
        self.temperature = config.get("temperature", 0.9)
        self.max_tokens = config.get("max_tokens", 50)
        self.conversation_history = []

    def generate_comment(self, context: str, danmu_context: str = "", recent_comments: list = None) -> str:
        """根据直播内容和弹幕上下文生成评论

        Args:
            context: 主播语音转录内容
            danmu_context: 最近的弹幕文本
            recent_comments: 最近发送过的评论列表（用于避免重复）

        Returns:
            生成的评论文本，失败返回空字符串
        """
        user_content = f"当前直播内容：{context}" if context else "当前直播内容：(无语音转录)"
        if danmu_context:
            user_content += f"\n\n最近弹幕：{danmu_context}"
        if recent_comments:
            user_content += f"\n\n你最近发过的评论（不要重复，要换话题或换角度）：{recent_comments}"

        messages = [{"role": "system", "content": self.system_prompt}]
        # 保留最近的对话历史
        messages.extend(self.conversation_history[-6:])
        messages.append({"role": "user", "content": user_content})

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            comment = response.choices[0].message.content.strip()

            # 更新对话历史
            self.conversation_history.append(
                {"role": "user", "content": user_content}
            )
            self.conversation_history.append(
                {"role": "assistant", "content": comment}
            )

            # 控制历史长度
            if len(self.conversation_history) > 20:
                self.conversation_history = self.conversation_history[-10:]

            print(f"[LLMClient] 生成评论: {repr(comment)}")
            return comment
        except Exception as e:
            print(f"[LLMClient] API调用错误: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            return ""

    def update_config(self, config: dict):
        """更新配置并重建客户端"""
        self.__init__(config)

    def clear_history(self):
        """清除对话历史"""
        self.conversation_history = []
