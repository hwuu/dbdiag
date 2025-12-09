"""会话管理 API 接口

支持 GAR2 诊断算法。
"""
from fastapi import APIRouter, HTTPException

# 从 chat 模块导入共享的会话管理器
from dbdiag.api.chat import _session_managers

# 创建路由
router = APIRouter()


@router.get("/sessions")
async def list_sessions(limit: int = 10):
    """
    列出当前活跃的会话

    返回当前内存中的活跃会话列表。
    注意：GAR2 会话存储在内存中，服务重启后会丢失。
    """
    sessions = []
    for session_id, dialogue_manager in list(_session_managers.items())[:limit]:
        session = dialogue_manager.get_session()
        if session:
            sessions.append({
                "session_id": session_id,
                "user_problem": session.user_problem,
                "turn_count": session.turn_count,
                "observations_count": len(session.symptom.observations),
                "hypotheses_count": len(session.hypotheses),
            })

    return {"sessions": sessions, "total": len(_session_managers)}


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """
    获取会话详情

    获取指定会话的详细信息，包括观察、假设等。
    """
    dialogue_manager = _session_managers.get(session_id)
    if not dialogue_manager:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")

    session = dialogue_manager.get_session()
    if not session:
        raise HTTPException(status_code=404, detail="会话状态异常")

    # 构建响应
    return {
        "session_id": session_id,
        "user_problem": session.user_problem,
        "turn_count": session.turn_count,
        "observations": [
            {
                "id": obs.id,
                "description": obs.description,
                "source": obs.source,
                "matched_phenomenon_id": obs.matched_phenomenon_id,
                "match_score": obs.match_score,
            }
            for obs in session.symptom.observations
        ],
        "matched_phenomenon_ids": list(session.symptom.get_matched_phenomenon_ids()),
        "blocked_phenomenon_ids": list(session.symptom.blocked_phenomenon_ids),
        "blocked_root_cause_ids": list(session.symptom.blocked_root_cause_ids),
        "hypotheses": [
            {
                "root_cause_id": hyp.root_cause_id,
                "confidence": hyp.confidence,
                "contributing_phenomena": hyp.contributing_phenomena,
            }
            for hyp in session.hypotheses
        ],
        "recommended_phenomenon_ids": session.recommended_phenomenon_ids,
    }


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """
    删除会话

    删除指定的诊断会话，释放资源。
    """
    if session_id in _session_managers:
        del _session_managers[session_id]
        return {"message": "会话已删除", "session_id": session_id}
    else:
        raise HTTPException(status_code=404, detail="会话不存在")
