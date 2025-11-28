"""数据导入脚本

从 JSON 文件导入工单数据到 SQLite 数据库

V2 架构变更：
- import_tickets_v2: 导入到 raw_tickets 和 raw_anomalies 表（推荐）
- import_tickets: V1 导入，标记为 deprecated
"""
import json
import sqlite3
import warnings
from pathlib import Path
from typing import Optional, Dict, List, Any


def import_tickets_v2(data_path: str, db_path: Optional[str] = None) -> None:
    """
    V2 导入：从 JSON 文件导入工单数据到原始数据表

    导入到 raw_tickets 和 raw_anomalies 表，用于后续 rebuild-index 处理。

    Args:
        data_path: JSON 数据文件路径（V2 格式，包含 anomalies 字段）
        db_path: 数据库文件路径，默认为 data/tickets.db
    """
    if db_path is None:
        project_root = Path(__file__).parent.parent
        db_path = str(project_root / "data" / "tickets.db")

    data_path = Path(data_path)

    if not data_path.exists():
        raise FileNotFoundError(f"数据文件不存在: {data_path}")

    if not Path(db_path).exists():
        raise FileNotFoundError(
            f"数据库文件不存在: {db_path}\n"
            f"请先运行: python -m app init"
        )

    print(f"[V2] 正在从 {data_path} 导入数据...")
    print(f"目标数据库: {db_path}")

    # 读取 JSON 数据
    with open(data_path, "r", encoding="utf-8") as f:
        tickets = json.load(f)

    if not isinstance(tickets, list):
        raise ValueError("JSON 数据格式错误：根元素必须是数组")

    print(f"共读取 {len(tickets)} 条工单")

    # 连接数据库
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        imported_count = 0
        skipped_count = 0
        anomaly_count = 0

        for ticket in tickets:
            try:
                # 导入工单和异常
                anomalies_imported = _import_ticket_v2(cursor, ticket)
                imported_count += 1
                anomaly_count += anomalies_imported
            except sqlite3.IntegrityError as e:
                # 主键冲突，跳过
                skipped_count += 1
                print(f"  [SKIP] {ticket.get('ticket_id')}: {e}")
            except Exception as e:
                print(f"  [ERROR] 导入失败 {ticket.get('ticket_id')}: {e}")
                raise

        conn.commit()

        print(f"\n[OK] V2 导入完成")
        print(f"  成功导入: {imported_count} 条工单")
        print(f"  导入异常: {anomaly_count} 条")
        print(f"  跳过重复: {skipped_count} 条")

        # 显示统计信息
        cursor.execute("SELECT COUNT(*) FROM raw_tickets")
        total_tickets = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM raw_anomalies")
        total_anomalies = cursor.fetchone()[0]

        print(f"\n数据库统计 (V2 原始数据):")
        print(f"  raw_tickets: {total_tickets}")
        print(f"  raw_anomalies: {total_anomalies}")

    except Exception as e:
        print(f"\n[ERROR] 导入失败: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


def _import_ticket_v2(cursor: sqlite3.Cursor, ticket: Dict[str, Any]) -> int:
    """
    V2: 导入单个工单及其异常到原始数据表

    Args:
        cursor: 数据库游标
        ticket: 工单数据字典

    Returns:
        导入的异常数量
    """
    ticket_id = ticket["ticket_id"]
    metadata = ticket.get("metadata", {})
    description = ticket["description"]
    root_cause = ticket["root_cause"]
    solution = ticket["solution"]
    anomalies = ticket.get("anomalies", [])

    # 插入到 raw_tickets
    cursor.execute(
        """
        INSERT INTO raw_tickets (ticket_id, metadata_json, description, root_cause, solution)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            ticket_id,
            json.dumps(metadata, ensure_ascii=False) if metadata else None,
            description,
            root_cause,
            solution,
        ),
    )

    # 插入异常到 raw_anomalies
    for index, anomaly in enumerate(anomalies):
        anomaly_id = f"{ticket_id}_anomaly_{index + 1}"

        cursor.execute(
            """
            INSERT INTO raw_anomalies (
                id,
                ticket_id,
                anomaly_index,
                description,
                observation_method,
                why_relevant
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                anomaly_id,
                ticket_id,
                index + 1,
                anomaly["description"],
                anomaly["observation_method"],
                anomaly["why_relevant"],
            ),
        )

    return len(anomalies)


def import_tickets(data_path: str, db_path: Optional[str] = None) -> None:
    """
    从 JSON 文件导入工单数据

    DEPRECATED: 请使用 import_tickets_v2 导入到 V2 原始数据表。

    Args:
        data_path: JSON 数据文件路径
        db_path: 数据库文件路径，默认为 data/tickets.db
    """
    warnings.warn(
        "import_tickets is deprecated. Use import_tickets_v2 instead.",
        DeprecationWarning,
        stacklevel=2
    )
    if db_path is None:
        # 默认使用项目根目录下的 data/tickets.db
        project_root = Path(__file__).parent.parent
        db_path = str(project_root / "data" / "tickets.db")

    data_path = Path(data_path)

    if not data_path.exists():
        raise FileNotFoundError(f"数据文件不存在: {data_path}")

    if not Path(db_path).exists():
        raise FileNotFoundError(
            f"数据库文件不存在: {db_path}\n"
            f"请先运行: python -m app init"
        )

    print(f"正在从 {data_path} 导入数据...")
    print(f"目标数据库: {db_path}")

    # 读取 JSON 数据
    with open(data_path, "r", encoding="utf-8") as f:
        tickets = json.load(f)

    if not isinstance(tickets, list):
        raise ValueError("JSON 数据格式错误：根元素必须是数组")

    print(f"共读取 {len(tickets)} 条工单")

    # 连接数据库
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        imported_count = 0
        skipped_count = 0

        for ticket in tickets:
            try:
                # 导入工单和诊断步骤
                _import_ticket(cursor, ticket)
                imported_count += 1
            except sqlite3.IntegrityError as e:
                # 主键冲突，跳过
                skipped_count += 1
                print(f"  [SKIP] {ticket.get('ticket_id')}: {e}")
            except Exception as e:
                print(f"  [ERROR] 导入失败 {ticket.get('ticket_id')}: {e}")
                raise

        conn.commit()

        print(f"\n[OK] 导入完成")
        print(f"  成功导入: {imported_count} 条")
        print(f"  跳过重复: {skipped_count} 条")

        # 显示统计信息
        cursor.execute("SELECT COUNT(*) FROM tickets")
        total_tickets = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM diagnostic_steps")
        total_steps = cursor.fetchone()[0]

        print(f"\n数据库统计:")
        print(f"  工单总数: {total_tickets}")
        print(f"  诊断步骤总数: {total_steps}")

    except Exception as e:
        print(f"\n[ERROR] 导入失败: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


def _import_ticket(cursor: sqlite3.Cursor, ticket: Dict[str, Any]) -> None:
    """
    导入单个工单及其诊断步骤

    Args:
        cursor: 数据库游标
        ticket: 工单数据字典
    """
    ticket_id = ticket["ticket_id"]
    metadata = ticket.get("metadata", {})
    description = ticket["description"]
    root_cause = ticket["root_cause"]
    solution = ticket["solution"]
    diagnostic_steps = ticket.get("diagnostic_steps", [])

    # 插入工单
    cursor.execute(
        """
        INSERT INTO tickets (ticket_id, metadata_json, description, root_cause, solution)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            ticket_id,
            json.dumps(metadata, ensure_ascii=False),
            description,
            root_cause,
            solution,
        ),
    )

    # 插入诊断步骤
    for index, step in enumerate(diagnostic_steps):
        step_id = f"{ticket_id}_step_{index + 1}"

        cursor.execute(
            """
            INSERT INTO diagnostic_steps (
                step_id,
                ticket_id,
                step_index,
                observed_fact,
                observation_method,
                analysis_result,
                ticket_description,
                ticket_root_cause
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                step_id,
                ticket_id,
                index + 1,
                step["observed_fact"],
                step["observation_method"],
                step["analysis_result"],
                description,  # 冗余工单描述
                root_cause,  # 冗余根因
            ),
        )


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法: python import_tickets.py <data_path> [db_path]")
        sys.exit(1)

    data_path = sys.argv[1]
    db_path = sys.argv[2] if len(sys.argv) > 2 else None

    import_tickets(data_path, db_path)
