"""Gradio 交互界面

提供友好的 Web UI 进行数据库问题诊断
"""
import gradio as gr
from pathlib import Path
from typing import List, Tuple

from app.core.dialogue_manager import DialogueManager
from app.utils.config import load_config


# 初始化对话管理器
config = load_config()
db_path = str(Path("data") / "tickets.db")
dialogue_manager = DialogueManager(db_path, config)

# 全局变量存储当前会话 ID
current_session_id = None


def start_diagnosis(problem: str) -> Tuple[str, str]:
    """
    开始诊断

    Args:
        problem: 用户问题描述

    Returns:
        (助手回复, 会话信息)
    """
    global current_session_id

    if not problem or not problem.strip():
        return "请输入您遇到的数据库问题。", ""

    try:
        # 开始新对话
        response = dialogue_manager.start_conversation(problem.strip())
        current_session_id = response["session_id"]

        # 构建回复
        assistant_message = response["message"]

        # 会话信息
        session_info = f"会话 ID: {current_session_id}"

        return assistant_message, session_info

    except Exception as e:
        return f"错误: {str(e)}", ""


def continue_diagnosis(user_message: str, chat_history: List) -> Tuple[List, str]:
    """
    继续诊断

    Args:
        user_message: 用户消息
        chat_history: 聊天历史

    Returns:
        (更新后的聊天历史, 清空的输入框)
    """
    global current_session_id

    if not current_session_id:
        chat_history.append(("请先输入问题描述并点击\"开始诊断\"", None))
        return chat_history, ""

    if not user_message or not user_message.strip():
        return chat_history, ""

    try:
        # 添加用户消息到历史
        chat_history.append((user_message, None))

        # 继续对话
        response = dialogue_manager.continue_conversation(
            current_session_id, user_message.strip()
        )

        # 添加助手回复到历史
        assistant_message = response["message"]
        chat_history[-1] = (user_message, assistant_message)

        return chat_history, ""

    except Exception as e:
        chat_history[-1] = (user_message, f"错误: {str(e)}")
        return chat_history, ""


def reset_session():
    """重置会话"""
    global current_session_id
    current_session_id = None
    return [], "", ""


def create_ui():
    """创建 Gradio UI"""

    with gr.Blocks(title="数据库运维问题诊断助手") as demo:
        gr.Markdown(
            """
        # 数据库运维问题诊断助手

        基于多假设追踪的智能诊断系统，帮助您快速定位数据库问题的根本原因。

        **使用方法：**
        1. 在下方输入框中描述您遇到的数据库问题
        2. 点击"开始诊断"按钮
        3. 根据系统推荐，执行诊断步骤并反馈结果
        4. 系统会逐步缩小根因范围，直到定位问题
        """
        )

        with gr.Row():
            with gr.Column(scale=3):
                # 问题输入区
                with gr.Group():
                    gr.Markdown("### 📝 问题描述")
                    problem_input = gr.Textbox(
                        label="",
                        placeholder="例如：生产环境查询突然变慢，原来5秒现在要30秒...",
                        lines=3,
                    )
                    with gr.Row():
                        start_btn = gr.Button("🚀 开始诊断", variant="primary", size="lg")
                        reset_btn = gr.Button("🔄 重新开始", size="lg")

                # 初始响应区
                with gr.Group():
                    gr.Markdown("### 🤖 诊断建议")
                    initial_response = gr.Markdown("")

            with gr.Column(scale=1):
                # 会话信息
                gr.Markdown("### ℹ️ 会话信息")
                session_info = gr.Textbox(label="", lines=2, interactive=False)

        # 对话区
        gr.Markdown("### 💬 诊断对话")
        chatbot = gr.Chatbot(
            label="",
            height=400,
            show_label=False,
            avatar_images=(None, "https://em-content.zobj.net/thumbs/120/apple/354/robot_1f916.png"),
        )

        with gr.Row():
            user_input = gr.Textbox(
                label="",
                placeholder="输入观察结果或回答问题...",
                scale=4,
            )
            send_btn = gr.Button("发送", variant="primary", scale=1)

        gr.Markdown(
            """
        ---
        **提示：**
        - 请尽可能详细描述问题的症状和表现
        - 执行系统推荐的诊断步骤后，将结果反馈给系统
        - 系统会根据您的反馈动态调整诊断方向
        """
        )

        # 事件绑定
        start_btn.click(
            fn=start_diagnosis,
            inputs=[problem_input],
            outputs=[initial_response, session_info],
        )

        send_btn.click(
            fn=continue_diagnosis,
            inputs=[user_input, chatbot],
            outputs=[chatbot, user_input],
        )

        user_input.submit(
            fn=continue_diagnosis,
            inputs=[user_input, chatbot],
            outputs=[chatbot, user_input],
        )

        reset_btn.click(
            fn=reset_session,
            inputs=[],
            outputs=[chatbot, problem_input, initial_response],
        )

    return demo


def launch(share: bool = False, server_port: int = 7860):
    """
    启动 Gradio UI

    Args:
        share: 是否创建公共分享链接
        server_port: 服务端口
    """
    demo = create_ui()
    demo.launch(
        share=share,
        server_port=server_port,
        server_name="0.0.0.0",
        show_error=True,
    )


if __name__ == "__main__":
    launch()
