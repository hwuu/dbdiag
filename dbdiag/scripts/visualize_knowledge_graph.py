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

from dbdiag.dao import (
    RootCauseDAO,
    TicketDAO,
    PhenomenonDAO,
    TicketPhenomenonDAO,
    PhenomenonRootCauseDAO,
)


# 布局配置
LAYOUT_OPTIONS = {
    "force": """
    {
        "groups": {
            "ticket": {
                "color": {
                    "background": "#fdeaa8",
                    "border": "#f0d878",
                    "highlight": {"background": "#f1c40f", "border": "#d4ac0d"}
                },
                "shape": "square"
            },
            "phenomenon": {
                "color": {
                    "background": "#f5b7b1",
                    "border": "#e6a09a",
                    "highlight": {"background": "#e74c3c", "border": "#c0392b"}
                },
                "shape": "dot"
            },
            "root_cause": {
                "color": {
                    "background": "#aed6f1",
                    "border": "#85c1e9",
                    "highlight": {"background": "#3498db", "border": "#2980b9"}
                },
                "shape": "dot"
            }
        },
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
        "edges": {
            "smooth": {"type": "continuous"},
            "color": {"highlight": "#ff0000"},
            "selectionWidth": 3
        },
        "interaction": {"hover": true, "selectConnectedEdges": true, "hoverConnectedEdges": true}
    }
    """,
    "hierarchical": """
    {
        "groups": {
            "ticket": {
                "color": {
                    "background": "#fdeaa8",
                    "border": "#f0d878",
                    "highlight": {"background": "#f1c40f", "border": "#d4ac0d"}
                },
                "shape": "square"
            },
            "phenomenon": {
                "color": {
                    "background": "#f5b7b1",
                    "border": "#e6a09a",
                    "highlight": {"background": "#e74c3c", "border": "#c0392b"}
                },
                "shape": "dot"
            },
            "root_cause": {
                "color": {
                    "background": "#aed6f1",
                    "border": "#85c1e9",
                    "highlight": {"background": "#3498db", "border": "#2980b9"}
                },
                "shape": "dot"
            }
        },
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
        "edges": {
            "smooth": {"type": "cubicBezier"},
            "color": {"highlight": "#ff0000"},
            "selectionWidth": 3
        },
        "interaction": {"hover": true, "selectConnectedEdges": true, "hoverConnectedEdges": true}
    }
    """,
    "tree": """
    {
        "groups": {
            "ticket": {
                "color": {
                    "background": "#fdeaa8",
                    "border": "#f0d878",
                    "highlight": {"background": "#f1c40f", "border": "#d4ac0d"}
                },
                "shape": "square"
            },
            "phenomenon": {
                "color": {
                    "background": "#f5b7b1",
                    "border": "#e6a09a",
                    "highlight": {"background": "#e74c3c", "border": "#c0392b"}
                },
                "shape": "dot"
            },
            "root_cause": {
                "color": {
                    "background": "#aed6f1",
                    "border": "#85c1e9",
                    "highlight": {"background": "#3498db", "border": "#2980b9"}
                },
                "shape": "dot"
            }
        },
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
        "edges": {
            "smooth": {"type": "cubicBezier"},
            "color": {"highlight": "#ff0000"},
            "selectionWidth": 3
        },
        "interaction": {"hover": true, "selectConnectedEdges": true, "hoverConnectedEdges": true}
    }
    """,
    "radial": """
    {
        "groups": {
            "ticket": {
                "color": {
                    "background": "#fdeaa8",
                    "border": "#f0d878",
                    "highlight": {"background": "#f1c40f", "border": "#d4ac0d"}
                },
                "shape": "square"
            },
            "phenomenon": {
                "color": {
                    "background": "#f5b7b1",
                    "border": "#e6a09a",
                    "highlight": {"background": "#e74c3c", "border": "#c0392b"}
                },
                "shape": "dot"
            },
            "root_cause": {
                "color": {
                    "background": "#aed6f1",
                    "border": "#85c1e9",
                    "highlight": {"background": "#3498db", "border": "#2980b9"}
                },
                "shape": "dot"
            }
        },
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
        "edges": {
            "smooth": {"type": "continuous"},
            "color": {"highlight": "#ff0000"},
            "selectionWidth": 3
        },
        "interaction": {"hover": true, "selectConnectedEdges": true, "hoverConnectedEdges": true}
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
    phenomenon_root_cause_dao = PhenomenonRootCauseDAO(db_path)

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
    ticket_phenomenon_assocs = ticket_phenomenon_dao.get_all_associations()
    phenomenon_root_cause_assocs = phenomenon_root_cause_dao.get_all()

    # 添加工单节点 - 层级 0（最顶层）
    for ticket in tickets:
        ticket_id = ticket["ticket_id"]
        desc = ticket["description"]
        short_desc = desc[:20] + "..." if len(desc) > 20 else desc
        full_desc = desc[:100] + "..." if len(desc) > 100 else desc

        net.add_node(
            f"T:{ticket_id}",
            label=f"{ticket_id}\n{short_desc}",
            title=f"【工单】{ticket_id}\n\n{full_desc}",
            group="ticket",
            shape="square",
            size=30,
            level=0,
        )

    # 添加现象节点 - 层级 1（中间层）
    for phenomenon in phenomena:
        phenomenon_id = phenomenon["phenomenon_id"]
        desc = phenomenon["description"]
        short_desc = desc[:20] + "..." if len(desc) > 20 else desc

        net.add_node(
            f"P:{phenomenon_id}",
            label=f"{phenomenon_id}\n{short_desc}",
            title=f"【现象】{phenomenon_id}\n\n{desc}",
            group="phenomenon",
            shape="dot",
            size=20,
            level=1,
        )

    # 添加根因节点 - 层级 2（最底层）
    for root_cause in root_causes:
        rc_id = root_cause["root_cause_id"]
        desc = root_cause["description"]
        short_label = desc[:20] + "..." if len(desc) > 20 else desc
        net.add_node(
            f"RC:{rc_id}",
            label=f"{rc_id}\n{short_label}",
            title=f"【根因】{rc_id}\n{desc}",
            group="root_cause",
            shape="dot",
            size=35,
            level=2,
        )

    # 添加工单-现象关联边（工单 → 现象）
    for assoc in ticket_phenomenon_assocs:
        ticket_id = assoc["ticket_id"]
        phenomenon_id = assoc["phenomenon_id"]

        net.add_edge(
            f"T:{ticket_id}",
            f"P:{phenomenon_id}",
            color="#bdc3c7",
            width=1,
            title="关联现象",
        )

    # 添加现象-根因关联边（现象 → 根因，通过 phenomenon_root_causes）
    for assoc in phenomenon_root_cause_assocs:
        phenomenon_id = assoc["phenomenon_id"]
        root_cause_id = assoc["root_cause_id"]
        ticket_count = assoc.get("ticket_count", 1)

        net.add_edge(
            f"P:{phenomenon_id}",
            f"RC:{root_cause_id}",
            color="#95a5a6",
            width=max(1, min(ticket_count, 5)),  # 根据 ticket_count 调整粗细
            title=f"支持根因 (出现 {ticket_count} 次)",
        )

    # 添加工单-根因关联边（工单 → 根因，虚线，表示最终确定的根因）
    for ticket in tickets:
        ticket_id = ticket["ticket_id"]
        root_cause_id = ticket["root_cause_id"]

        if root_cause_id:
            net.add_edge(
                f"T:{ticket_id}",
                f"RC:{root_cause_id}",
                color="#9b59b6",  # 紫色
                width=2,
                dashes=True,  # 虚线
                title="最终根因",
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

    # 添加高亮一度邻居的 JavaScript
    neighbor_highlight_script = """
    <script>
    // 等待 network 初始化完成
    setTimeout(function() {
        if (typeof network !== 'undefined') {
            var originalNodeColors = {};
            var originalEdgeColors = {};

            // 保存所有节点的原始颜色
            var allNodes = nodes.get();
            allNodes.forEach(function(node) {
                originalNodeColors[node.id] = {
                    color: node.color,
                    borderWidth: node.borderWidth || 1
                };
            });

            // 保存所有边的原始颜色
            var allEdges = edges.get();
            allEdges.forEach(function(edge) {
                originalEdgeColors[edge.id] = {
                    color: edge.color,
                    width: edge.width || 1
                };
            });

            network.on("selectNode", function(params) {
                var selectedNodeId = params.nodes[0];
                var connectedNodes = network.getConnectedNodes(selectedNodeId);
                var connectedEdges = network.getConnectedEdges(selectedNodeId);

                // 更新所有节点
                var nodeUpdates = [];
                allNodes.forEach(function(node) {
                    if (node.id === selectedNodeId) {
                        // 选中节点：加粗边框
                        nodeUpdates.push({
                            id: node.id,
                            borderWidth: 4
                        });
                    } else if (connectedNodes.indexOf(node.id) !== -1) {
                        // 邻居节点：加粗边框
                        nodeUpdates.push({
                            id: node.id,
                            borderWidth: 3
                        });
                    } else {
                        // 其他节点：变成灰色
                        nodeUpdates.push({
                            id: node.id,
                            color: {
                                background: "#e0e0e0",
                                border: "#c0c0c0"
                            }
                        });
                    }
                });
                nodes.update(nodeUpdates);

                // 更新所有边
                var edgeUpdates = [];
                allEdges.forEach(function(edge) {
                    if (connectedEdges.indexOf(edge.id) === -1) {
                        // 非相关边：变淡
                        edgeUpdates.push({
                            id: edge.id,
                            color: {color: "#e8e8e8", highlight: "#e8e8e8"},
                            width: 0.5
                        });
                    }
                });
                edges.update(edgeUpdates);
            });

            network.on("deselectNode", function(params) {
                // 恢复所有节点
                var nodeUpdates = [];
                allNodes.forEach(function(node) {
                    nodeUpdates.push({
                        id: node.id,
                        color: originalNodeColors[node.id].color,
                        borderWidth: originalNodeColors[node.id].borderWidth
                    });
                });
                nodes.update(nodeUpdates);

                // 恢复所有边
                var edgeUpdates = [];
                allEdges.forEach(function(edge) {
                    edgeUpdates.push({
                        id: edge.id,
                        color: originalEdgeColors[edge.id].color,
                        width: originalEdgeColors[edge.id].width
                    });
                });
                edges.update(edgeUpdates);
            });
        }
    }, 500);
    </script>
    """
    html_content = html_content.replace("</body>", f"{neighbor_highlight_script}</body>")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    # 统计信息
    print(f"知识图谱已生成: {output_path}")
    print(f"  - 工单节点: {len(tickets)}")
    print(f"  - 现象节点: {len(phenomena)}")
    print(f"  - 根因节点: {len(root_causes)}")
    print(f"  - 边: {len(ticket_phenomenon_assocs)} (工单→现象) + "
          f"{len(phenomenon_root_cause_assocs)} (现象→根因) + "
          f"{sum(1 for t in tickets if t['root_cause_id'])} (工单→根因虚线)")


def main():
    parser = argparse.ArgumentParser(
        description="生成知识图谱可视化 HTML",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
布局模式说明:
  force        力导向布局（默认），节点自动排斥/吸引，适合探索
  hierarchical 分层布局，从上到下：工单 → 现象 → 根因
  tree         树状布局，从左到右显示层级关系
  radial       径向布局，中心向外扩散

边类型说明:
  实线灰色    工单 → 现象（关联现象）
  实线灰色    现象 → 根因（支持关系，来自 phenomenon_root_causes）
  虚线紫色    工单 → 根因（最终确定的根因）

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
