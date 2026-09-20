"""Traffic summaries for admin-managed LDAP groups."""

from __future__ import annotations

from datetime import date, timedelta

from loguru import logger
from sqlalchemy import func
from sqlalchemy.orm import Session

from database.database import get_dynamic_models
from database.models.models import LdapGroup, LdapGroupMember


def _date_range(start_date: date, end_date: date):
    current = start_date
    while current <= end_date:
        yield current
        current += timedelta(days=1)


def _empty_result(start_date: date, end_date: date) -> dict:
    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "total_requests": 0,
        "total_bytes": 0,
        "groups": [],
        "selected_group": None,
        "selected_group_users": [],
    }


def get_group_traffic_summary(
    session: Session,
    start_date: date,
    end_date: date,
    selected_group_id: int | None = None,
) -> dict:
    """Aggregate traffic from daily tables and map it to managed LDAP groups."""
    result = _empty_result(start_date, end_date)
    if start_date > end_date:
        return result

    groups = session.query(LdapGroup).order_by(LdapGroup.name.asc()).all()
    members = session.query(LdapGroupMember).all()
    group_by_id = {group.id: group for group in groups}
    username_groups: dict[str, set[int]] = {}
    for member in members:
        username_groups.setdefault(member.username, set()).add(member.group_id)

    aggregate: dict[str, dict] = {}
    for group in groups:
        aggregate[str(group.id)] = {
            "id": group.id,
            "name": group.name,
            "source": group.source,
            "total_requests": 0,
            "total_bytes": 0,
            "user_count": 0,
            "users": {},
        }
    aggregate["ungrouped"] = {
        "id": None,
        "name": "__ungrouped__",
        "source": "system",
        "total_requests": 0,
        "total_bytes": 0,
        "user_count": 0,
        "users": {},
    }

    for current_date in _date_range(start_date, end_date):
        try:
            user_model, log_model = get_dynamic_models(current_date.strftime("%Y%m%d"))
            rows = (
                session.query(
                    user_model.username,
                    func.coalesce(func.sum(log_model.request_count), 0),
                    func.coalesce(func.sum(log_model.data_transmitted), 0),
                )
                .join(log_model, user_model.id == log_model.user_id)
                .filter(user_model.username != "-")
                .group_by(user_model.username)
                .all()
            )
        except Exception as exc:
            logger.debug("Skipping unavailable log table for {}: {}", current_date, exc)
            continue

        for username, requests, total_bytes in rows:
            requests = int(requests or 0)
            total_bytes = int(total_bytes or 0)
            target_ids = username_groups.get(username) or {None}
            for group_id in target_ids:
                key = str(group_id) if group_id is not None else "ungrouped"
                bucket = aggregate[key]
                bucket["total_requests"] += requests
                bucket["total_bytes"] += total_bytes
                user = bucket["users"].setdefault(
                    username,
                    {"username": username, "total_requests": 0, "total_bytes": 0},
                )
                user["total_requests"] += requests
                user["total_bytes"] += total_bytes

    result["total_requests"] = sum(
        item["total_requests"] for item in aggregate.values()
    )
    result["total_bytes"] = sum(item["total_bytes"] for item in aggregate.values())

    group_rows = []
    for item in aggregate.values():
        if item["id"] is None and not item["users"]:
            continue
        item["user_count"] = len(item["users"])
        item["users"] = sorted(
            item["users"].values(),
            key=lambda user: (-user["total_bytes"], user["username"].lower()),
        )
        group_rows.append(item)

    group_rows.sort(key=lambda group: (-group["total_bytes"], group["name"]))
    for item in group_rows:
        item["percentage"] = (
            (item["total_bytes"] * 100 / result["total_bytes"])
            if result["total_bytes"]
            else 0
        )
    result["groups"] = [
        {key: value for key, value in item.items() if key != "users"}
        for item in group_rows
    ]

    if selected_group_id is not None and selected_group_id in group_by_id:
        selected = aggregate[str(selected_group_id)]
        selected["user_count"] = len(selected["users"])
        selected_users_source = selected["users"]
        if isinstance(selected_users_source, dict):
            selected_users_source = selected_users_source.values()
        selected_users = sorted(
            selected_users_source,
            key=lambda user: (-user["total_bytes"], user["username"].lower()),
        )
        result["selected_group"] = {
            "id": selected_group_id,
            "name": group_by_id[selected_group_id].name,
            "source": group_by_id[selected_group_id].source,
            "total_requests": selected["total_requests"],
            "total_bytes": selected["total_bytes"],
            "percentage": (
                selected["total_bytes"] * 100 / result["total_bytes"]
                if result["total_bytes"]
                else 0
            ),
        }
        result["selected_group_users"] = selected_users

    return result
