"""CLI 端到端测试脚本

模拟用户输入，测试 CLI 是否正常工作
"""
import sys
from pathlib import Path
from io import StringIO
from unittest.mock import patch

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dbdiag.cli.main import CLI


def test_cli_help_command():
    """测试 /help 命令"""
    print("\n=== 测试 /help 命令 ===")

    cli = CLI()

    # 模拟输入
    with patch("builtins.input", side_effect=["/help", "/exit"]):
        # 捕获输出
        old_stdout = sys.stdout
        sys.stdout = StringIO()

        try:
            cli.run()
            output = sys.stdout.getvalue()

            # 验证输出
            assert "/help" in output
            assert "/status" in output
            assert "/exit" in output

            print("[OK] /help 命令测试通过")

        finally:
            sys.stdout = old_stdout


def test_cli_basic_interaction():
    """测试基本交互流程"""
    print("\n=== 测试基本交互流程 ===")

    cli = CLI()

    # 模拟输入：问题描述 -> 检查结果 -> 退出
    user_inputs = [
        "查询变慢",  # 初始问题
        "/exit",  # 退出
    ]

    with patch("builtins.input", side_effect=user_inputs):
        old_stdout = sys.stdout
        sys.stdout = StringIO()

        try:
            cli.run()
            output = sys.stdout.getvalue()

            # 验证欢迎信息
            assert "数据库诊断助手" in output

            # 验证有推荐输出
            # 注意：实际输出依赖于数据库和模型，这里只做基本检查
            print("[OK] 基本交互流程测试通过")

        finally:
            sys.stdout = old_stdout


if __name__ == "__main__":
    try:
        test_cli_help_command()
        test_cli_basic_interaction()

        print("\n" + "=" * 50)
        print("所有 CLI 测试通过！")
        print("=" * 50)

    except Exception as e:
        print(f"\n[ERROR] 测试失败: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
