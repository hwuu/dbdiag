"""dbdiag 命令行入口"""
import sys
from pathlib import Path

import click


@click.group()
def cli():
    """数据库运维问题诊断助手"""
    pass


@cli.command()
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


@cli.command("import")
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


@cli.command("rebuild-index")
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


@cli.command()
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
    click.echo("TODO: 实现 FastAPI 服务")
    # import uvicorn
    # from app.main import app
    # uvicorn.run(app, host=host, port=port)


@cli.command()
@click.option(
    "--share",
    is_flag=True,
    help="创建公共分享链接",
)
def ui(share: bool):
    """启动 Gradio UI"""
    click.echo("TODO: 实现 Gradio UI")
    # from ui.gradio_app import launch
    # launch(share=share)


if __name__ == "__main__":
    cli()
