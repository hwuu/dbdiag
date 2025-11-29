"""原始工单数据导入脚本

从 JSON 文件导入工单数据到 SQLite 数据库的原始数据表（raw_tickets, raw_anomalies）。
导入后需运行 rebuild-index 生成处理后的数据表。
"""
import json
from pathlib import Path
from typing import Optional

from dbdiag.dao import RawTicketDAO


def import_tickets(data_path: str, db_path: Optional[str] = None) -> None:
    """
    从 JSON 文件导入工单数据到原始数据表

    导入到 raw_tickets 和 raw_anomalies 表，用于后续 rebuild-index 处理。

    Args:
        data_path: JSON 数据文件路径（包含 anomalies 字段）
        db_path: 数据库文件路径，默认为 data/tickets.db
    """
    if db_path is None:
        project_root = Path(__file__).parent.parent.parent
        db_path = str(project_root / "data" / "tickets.db")

    data_path = Path(data_path)

    if not data_path.exists():
        raise FileNotFoundError(f"数据文件不存在: {data_path}")

    if not Path(db_path).exists():
        raise FileNotFoundError(
            f"数据库文件不存在: {db_path}\n"
            f"请先运行: python -m dbdiag init"
        )

    print(f"正在从 {data_path} 导入数据...")
    print(f"目标数据库: {db_path}")

    # 读取 JSON 数据
    with open(data_path, "r", encoding="utf-8") as f:
        tickets = json.load(f)

    if not isinstance(tickets, list):
        raise ValueError("JSON 数据格式错误：根元素必须是数组")

    print(f"共读取 {len(tickets)} 条工单")

    # 使用 DAO 导入
    raw_ticket_dao = RawTicketDAO(db_path)

    try:
        imported_count, skipped_count, anomaly_count = raw_ticket_dao.insert_batch(tickets)

        print(f"\n[OK] 导入完成")
        print(f"  成功导入: {imported_count} 条工单")
        print(f"  导入异常: {anomaly_count} 条")
        print(f"  跳过重复: {skipped_count} 条")

        # 显示统计信息
        total_tickets = raw_ticket_dao.count()

        print(f"\n数据库统计:")
        print(f"  raw_tickets: {total_tickets}")

    except Exception as e:
        print(f"\n[ERROR] 导入失败: {e}")
        raise


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法: python import_raw_tickets.py <data_path> [db_path]")
        sys.exit(1)

    data_path = sys.argv[1]
    db_path = sys.argv[2] if len(sys.argv) > 2 else None

    import_tickets(data_path, db_path)
