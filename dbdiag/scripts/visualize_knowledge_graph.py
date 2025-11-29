"""知识图谱可视化脚本

将 tickets.db 中的工单、现象、根因关系可视化为交互式 HTML。

支持的布局模式：
- force: 力导向布局（默认），节点自动排斥/吸引
- hierarchical: 分层布局，从上到下显示层级关系
- tree: 树状布局，从左到右显示
"""
import argparse
from pathlib import Path
from pyvis.network import Network

from dbdiag.dao import RootCauseDAO, TicketDAO, PhenomenonDAO, TicketPhenomenonDAO


# 布局配置
LAYOUT_OPTIONS = {
    "force": """
    {
        "physics": {
            "forceAtlas2Based": {
                "gravitationalConstant": -100,
                "centralGravity": 0.01,
                "springLength": 200,
                "springConstant": 0.08
            },
            "solver": "forceAtlas2Based",
            "stabilization": {"iterations": 150}
        },
        "nodes": {"font": {"size": 12}},
        "edges": {"smooth": {"type": "continuous"}}
    }
    """,
    "hierarchical": """
    {
        "layout": {
            "hierarchical": {
                "enabled": true,
                "direction": "UD",
                "sortMethod": "directed",
                "levelSeparation": 100,
                "nodeSpacing": 50,
                "treeSpacing": 80,
                "blockShifting": true,
                "edgeMinimization": true,
                "parentCentralization": true
            }
        },
        "physics": {
            "hierarchicalRepulsion": {
                "centralGravity": 0.5,
                "springLength": 80,
                "springConstant": 0.05,
                "nodeDistance": 80
            },
            "solver": "hierarchicalRepulsion"
        },
        "nodes": {"font": {"size": 12}},
        "edges": {"smooth": {"type": "cubicBezier"}}
    }
    """,
    "tree": """
    {
        "layout": {
            "hierarchical": {
                "enabled": true,
                "direction": "LR",
                "sortMethod": "directed",
                "levelSeparation": 150,
                "nodeSpacing": 40,
                "treeSpacing": 60,
                "blockShifting": true,
                "edgeMinimization": true,
                "parentCentralization": true
            }
        },
        "physics": {
            "hierarchicalRepulsion": {
                "centralGravity": 0.5,
                "springLength": 80,
                "springConstant": 0.05,
                "nodeDistance": 60
            },
            "solver": "hierarchicalRepulsion"
        },
        "nodes": {"font": {"size": 12}},
        "edges": {"smooth": {"type": "cubicBezier"}}
    }
    """,
    "radial": """
    {
        "physics": {
            "barnesHut": {
                "gravitationalConstant": -3000,
                "centralGravity": 0.5,
                "springLength": 150,
                "springConstant": 0.04
            },
            "solver": "barnesHut",
            "stabilization": {"iterations": 200}
        },
        "nodes": {"font": {"size": 12}},
        "edges": {"smooth": {"type": "continuous"}}
    }
    """,
}


def create_knowledge_graph(db_path: str, output_path: str, layout: str = "force"):
    """创建知识图谱可视化

    Args:
        db_path: 数据库路径
        output_path: 输出 HTML 路径
        layout: 布局模式 (force/hierarchical/tree/radial)
    """
    # 初始化 DAO
    root_cause_dao = RootCauseDAO(db_path)
    ticket_dao = TicketDAO(db_path)
    phenomenon_dao = PhenomenonDAO(db_path)
    ticket_phenomenon_dao = TicketPhenomenonDAO(db_path)

    # 创建网络图（占满整个视口）
    net = Network(
        height="100vh",
        width="100%",
        bgcolor="#ffffff",
        font_color="#333333",
        directed=True,
    )

    # 应用布局配置
    if layout not in LAYOUT_OPTIONS:
        print(f"警告: 未知布局 '{layout}'，使用默认 'force'")
        layout = "force"

    net.set_options(LAYOUT_OPTIONS[layout])
    print(f"使用布局: {layout}")

    # 1. 获取所有根因
    root_causes = root_cause_dao.get_all()

    # 2. 获取所有工单
    tickets = ticket_dao.get_all()

    # 3. 获取所有现象（不限制数量）
    phenomena = phenomenon_dao.get_all(limit=10000)

    # 4. 获取关联关系
    associations = ticket_phenomenon_dao.get_all_associations()

    # 添加根因节点（蓝色圆形，大号）- 层级 0
    for root_cause in root_causes:
        rc_id = root_cause["root_cause_id"]
        desc = root_cause["description"]
        short_label = desc[:20] + "..." if len(desc) > 20 else desc
        net.add_node(
            f"RC:{rc_id}",
            label=f"{rc_id}\n{short_label}",
            title=f"【根因】{rc_id}\n{desc}",
            color="#3498db",
            size=35,
            shape="dot",
            group="root_cause",
            level=0,  # 最顶层
        )

    # 添加工单节点（黄色正方形，中号）- 层级 1
    for ticket in tickets:
        ticket_id = ticket["ticket_id"]
        root_cause_id = ticket["root_cause_id"]
        desc = ticket["description"]
        short_desc = desc[:20] + "..." if len(desc) > 20 else desc
        full_desc = desc[:100] + "..." if len(desc) > 100 else desc

        net.add_node(
            f"T:{ticket_id}",
            label=f"{ticket_id}\n{short_desc}",
            title=f"【工单】{ticket_id}\n\n{full_desc}",
            color="#f1c40f",
            size=25,
            shape="square",
            group="ticket",
            level=1,  # 中间层
        )

        # 根因 → 工单
        if root_cause_id:
            net.add_edge(
                f"RC:{root_cause_id}",
                f"T:{ticket_id}",
                color="#95a5a6",
                width=2,
                title="根因",
            )

    # 添加现象节点（绿色，小号）- 层级 2
    for phenomenon in phenomena:
        phenomenon_id = phenomenon["phenomenon_id"]
        desc = phenomenon["description"]
        short_desc = desc[:20] + "..." if len(desc) > 20 else desc

        net.add_node(
            f"P:{phenomenon_id}",
            label=f"{phenomenon_id}\n{short_desc}",
            title=f"【现象】{phenomenon_id}\n\n{desc}",
            color="#2ecc71",
            size=15,
            shape="dot",
            group="phenomenon",
            level=2,  # 最底层
        )

    # 添加工单-现象关联边（工单 → 现象）
    for assoc in associations:
        ticket_id = assoc["ticket_id"]
        phenomenon_id = assoc["phenomenon_id"]

        net.add_edge(
            f"T:{ticket_id}",
            f"P:{phenomenon_id}",
            color="#bdc3c7",
            width=1,
            title="关联现象",
        )

    # 生成 HTML
    net.save_graph(output_path)

    # 后处理：让图表真正占满整个屏幕
    with open(output_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    # 添加全屏样式，移除默认边距和边框
    fullscreen_style = """
        <style>
            html, body {
                margin: 0;
                padding: 0;
                overflow: hidden;
                height: 100%;
                width: 100%;
            }
            center { display: none; }
            #mynetwork {
                border: none !important;
                position: absolute !important;
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
            }
        </style>
    """
    html_content = html_content.replace("<head>", f"<head>{fullscreen_style}")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    # 统计信息
    print(f"知识图谱已生成: {output_path}")
    print(f"  - 根因节点: {len(root_causes)}")
    print(f"  - 工单节点: {len(tickets)}")
    print(f"  - 现象节点: {len(phenomena)}")
    print(f"  - 关联边: {len(associations)} (工单-现象) + {len(tickets)} (工单-根因)")


def main():
    parser = argparse.ArgumentParser(
        description="生成知识图谱可视化 HTML",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
布局模式说明:
  force        力导向布局（默认），节点自动排斥/吸引，适合探索
  hierarchical 分层布局，从上到下：根因 → 工单 → 现象
  tree         树状布局，从左到右显示层级关系
  radial       径向布局，中心向外扩散

示例:
  python scripts/visualize_knowledge_graph.py
  python scripts/visualize_knowledge_graph.py --layout hierarchical
  python scripts/visualize_knowledge_graph.py --layout tree -o output.html
        """,
    )
    parser.add_argument(
        "--layout", "-l",
        choices=["force", "hierarchical", "tree", "radial"],
        default="force",
        help="布局模式 (default: force)",
    )
    parser.add_argument(
        "--output", "-o",
        default="data/knowledge_graph.html",
        help="输出文件路径 (default: data/knowledge_graph.html)",
    )
    parser.add_argument(
        "--db",
        default="data/tickets.db",
        help="数据库路径 (default: data/tickets.db)",
    )

    args = parser.parse_args()

    db_path = Path(args.db)
    output_path = Path(args.output)

    if not db_path.exists():
        print(f"错误: 数据库文件不存在 {db_path}")
        return

    create_knowledge_graph(str(db_path), str(output_path), args.layout)


if __name__ == "__main__":
    main()
