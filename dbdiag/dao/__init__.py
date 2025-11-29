"""DAO 模块

提供数据访问对象，统一管理数据库操作
"""

from dbdiag.dao.base import BaseDAO
from dbdiag.dao.phenomenon_dao import PhenomenonDAO
from dbdiag.dao.ticket_dao import TicketDAO, TicketPhenomenonDAO, PhenomenonRootCauseDAO
from dbdiag.dao.root_cause_dao import RootCauseDAO
from dbdiag.dao.session_dao import SessionDAO
from dbdiag.dao.raw_anomaly_dao import RawAnomalyDAO
from dbdiag.dao.raw_ticket_dao import RawTicketDAO
from dbdiag.dao.index_builder_dao import IndexBuilderDAO

__all__ = [
    "BaseDAO",
    "PhenomenonDAO",
    "TicketDAO",
    "TicketPhenomenonDAO",
    "PhenomenonRootCauseDAO",
    "RootCauseDAO",
    "SessionDAO",
    "RawAnomalyDAO",
    "RawTicketDAO",
    "IndexBuilderDAO",
]
