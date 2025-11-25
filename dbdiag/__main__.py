"""dbdiag 命令行入口

使用方式：
    python -m dbdiag cli            # 启动交互式 CLI 诊断
    python -m dbdiag api            # 启动 FastAPI 服务
    python -m dbdiag ui             # 启动 Gradio UI
    python -m dbdiag init           # 初始化数据库
    python -m dbdiag import         # 导入工单数据
    python -m dbdiag rebuild-index  # 重建向量索引
"""
import sys
from pathlib import Path

import click


@click.group()
def main():
    """数据库运维问题诊断助手"""
    pass


@main.command("cli")
def interactive_cli():
    """启动交互式命令行诊断（推荐）"""
    from cli.main import main as cli_main
    cli_main()


@main.command("api")
@click.option(
    "--host",
    default="127.0.0.1",
    help="服务监听地址",
)
@click.option(
    "--port",
    default=8000,
    type=int,
    help="服务监听端口",
)
def serve(host: str, port: int):
    """启动 FastAPI 服务"""
    import uvicorn
    from api.main import app

    click.echo(f"正在启动服务: http://{host}:{port}")
    click.echo(f"API 文档: http://{host}:{port}/docs")
    uvicorn.run(app, host=host, port=port)


@main.command("ui")
@click.option(
    "--share",
    is_flag=True,
    help="创建公共分享链接",
)
@click.option(
    "--port",
    default=7860,
    type=int,
    help="服务监听端口",
)
def ui_launch(share: bool, port: int):
    """启动 Gradio UI"""
    from ui.main import launch

    click.echo(f"正在启动 Gradio UI: http://127.0.0.1:{port}")
    launch(share=share, server_port=port)


@main.command()
@click.option(
    "--db",
    default=None,
    help="数据库文件路径（默认: data/tickets.db）",
)
def init(db: str):
    """初始化数据库（仅创建表结构，不导入数据）"""
    from scripts.init_db import init_database

    try:
        init_database(db)
        click.echo("\n[OK] 数据库初始化成功")
    except Exception as e:
        click.echo(f"\n[ERROR] 初始化失败: {e}", err=True)
        sys.exit(1)


@main.command("import")
@click.option(
    "--data",
    required=True,
    type=click.Path(exists=True),
    help="工单数据文件路径（JSON 格式）",
)
@click.option(
    "--db",
    default=None,
    help="数据库文件路径（默认: data/tickets.db）",
)
def import_data(data: str, db: str):
    """导入工单数据到数据库"""
    from scripts.import_tickets import import_tickets

    try:
        import_tickets(data, db)
        click.echo("\n[OK] 数据导入成功")
    except Exception as e:
        click.echo(f"\n[ERROR] 导入失败: {e}", err=True)
        sys.exit(1)


@main.command("rebuild-index")
@click.option(
    "--db",
    default=None,
    help="数据库文件路径（默认: data/tickets.db）",
)
@click.option(
    "--config",
    default=None,
    help="配置文件路径（默认: config.yaml）",
)
def rebuild_index(db: str, config: str):
    """重建向量索引（调用 Embedding API 生成向量）"""
    from scripts.build_embeddings import build_embeddings

    try:
        build_embeddings(db, config)
        click.echo("\n[OK] 向量索引重建成功")
    except Exception as e:
        click.echo(f"\n[ERROR] 重建失败: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
