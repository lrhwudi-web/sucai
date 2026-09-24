from __future__ import annotations

from urllib.parse import urlencode

import requests


AUTHORIZE_URL = "https://login.dingtalk.com/oauth2/auth"
TOKEN_URL = "https://api.dingtalk.com/v1.0/oauth2/userAccessToken"
PROFILE_URL = "https://api.dingtalk.com/v1.0/contact/users/me"
APP_TOKEN_URL = "https://api.dingtalk.com/v1.0/oauth2/accessToken"
USER_BY_UNION_URL = "https://oapi.dingtalk.com/topapi/user/getbyunionid"
USER_DETAIL_URL = "https://oapi.dingtalk.com/topapi/v2/user/get"
DEPARTMENT_DETAIL_URL = "https://oapi.dingtalk.com/topapi/v2/department/get"
DEPARTMENT_LIST_URL = "https://oapi.dingtalk.com/topapi/v2/department/listsub"
DEPARTMENT_USERS_URL = "https://oapi.dingtalk.com/topapi/user/listsimple"
WORK_NOTIFICATION_URL = "https://oapi.dingtalk.com/topapi/message/corpconversation/asyncsend_v2"


class DingTalkAuthError(RuntimeError):
    """Raised when DingTalk cannot complete the OAuth login flow."""


def authorization_url(client_id: str, redirect_uri: str, state: str) -> str:
    query = urlencode(
        {
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "client_id": client_id,
            "scope": "openid",
            "state": state,
            "prompt": "consent",
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


def exchange_code(code: str, client_id: str, client_secret: str) -> str:
    try:
        response = requests.post(
            TOKEN_URL,
            json={
                "clientId": client_id,
                "clientSecret": client_secret,
                "code": code,
                "grantType": "authorization_code",
            },
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise DingTalkAuthError("DingTalk token exchange failed") from exc
    access_token = str(payload.get("accessToken") or "").strip()
    if not access_token:
        raise DingTalkAuthError("DingTalk did not return a user access token")
    return access_token


def get_user_profile(access_token: str) -> dict:
    try:
        response = requests.get(
            PROFILE_URL,
            headers={"x-acs-dingtalk-access-token": access_token},
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise DingTalkAuthError("DingTalk user profile request failed") from exc
    if not isinstance(payload, dict) or not profile_subject(payload):
        raise DingTalkAuthError("DingTalk did not return a stable user identity")
    return payload


def _post_json(url: str, *, action: str, **kwargs) -> dict:
    try:
        response = requests.post(url, timeout=15, **kwargs)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise DingTalkAuthError(f"DingTalk {action} failed") from exc
    if not isinstance(payload, dict):
        raise DingTalkAuthError(f"DingTalk {action} returned an invalid response")
    errcode = payload.get("errcode")
    if errcode not in (None, 0):
        raise DingTalkAuthError(f"DingTalk {action} was rejected")
    return payload


def get_app_access_token(client_id: str, client_secret: str) -> str:
    payload = _post_json(
        APP_TOKEN_URL,
        action="application token request",
        json={"appKey": client_id, "appSecret": client_secret},
    )
    token = str(payload.get("accessToken") or payload.get("access_token") or "").strip()
    if not token:
        raise DingTalkAuthError("DingTalk did not return an application access token")
    return token


def send_work_notification(
    user_ids: list[str],
    content: str,
    client_id: str,
    client_secret: str,
    agent_id: str,
) -> dict[str, str | int]:
    recipients = list(dict.fromkeys(str(user_id).strip() for user_id in user_ids if str(user_id).strip()))
    if not recipients:
        raise ValueError("DingTalk work notification requires at least one recipient")
    message = str(content).strip()
    if not message:
        raise ValueError("DingTalk work notification content cannot be empty")
    try:
        numeric_agent_id = int(str(agent_id).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError("DingTalk work notification agent ID must be numeric") from exc
    if numeric_agent_id <= 0:
        raise ValueError("DingTalk work notification agent ID must be numeric")

    access_token = get_app_access_token(client_id, client_secret)
    payload = _post_json(
        WORK_NOTIFICATION_URL,
        action="work notification request",
        params={"access_token": access_token},
        json={
            "agent_id": numeric_agent_id,
            "userid_list": ",".join(recipients),
            "msg": {"msgtype": "text", "text": {"content": message}},
        },
    )
    task_id = str(payload.get("task_id") or payload.get("taskId") or "").strip()
    if not task_id:
        raise DingTalkAuthError("DingTalk did not return a work notification task ID")
    return {"task_id": task_id, "recipient_count": len(recipients)}


def get_organization_membership(profile: dict, client_id: str, client_secret: str) -> dict:
    union_id = profile_union_id(profile)
    if not union_id:
        raise DingTalkAuthError("DingTalk profile is missing unionId for department lookup")
    access_token = get_app_access_token(client_id, client_secret)
    params = {"access_token": access_token}
    lookup = _post_json(
        USER_BY_UNION_URL,
        action="unionId lookup",
        params=params,
        json={"unionid": union_id},
    )
    user_id = str((lookup.get("result") or {}).get("userid") or "").strip()
    if not user_id:
        raise DingTalkAuthError("DingTalk could not resolve the organization user")
    detail = _post_json(
        USER_DETAIL_URL,
        action="organization user lookup",
        params=params,
        json={"userid": user_id, "language": "zh_CN"},
    )
    department_ids = (detail.get("result") or {}).get("dept_id_list") or []
    names: list[str] = []
    for department_id in department_ids:
        department = _post_json(
            DEPARTMENT_DETAIL_URL,
            action="department lookup",
            params=params,
            json={"dept_id": department_id, "language": "zh_CN"},
        )
        name = str((department.get("result") or {}).get("name") or "").strip()
        if name and name not in names:
            names.append(name)
    return {"user_id": user_id, "department_names": names}


def get_department_names(profile: dict, client_id: str, client_secret: str) -> list[str]:
    return get_organization_membership(profile, client_id, client_secret)["department_names"]


def get_organization_directory(client_id: str, client_secret: str) -> dict:
    access_token = get_app_access_token(client_id, client_secret)
    params = {"access_token": access_token}
    departments: list[dict] = [
        {"id": "1", "name": "全部组织", "parent_id": "", "depth": 0},
    ]
    members: dict[str, dict] = {}
    queue: list[tuple[str, int]] = [("1", 0)]
    visited: set[str] = set()

    while queue:
        department_id, depth = queue.pop(0)
        if department_id in visited:
            continue
        visited.add(department_id)
        if len(visited) > 1000:
            raise DingTalkAuthError("DingTalk organization directory is unexpectedly large")

        child_payload = _post_json(
            DEPARTMENT_LIST_URL,
            action="department tree lookup",
            params=params,
            json={"dept_id": int(department_id), "language": "zh_CN"},
        )
        for child in child_payload.get("result") or []:
            child_id = str(child.get("dept_id") or "").strip()
            name = str(child.get("name") or "").strip()
            if not child_id or not name:
                continue
            departments.append(
                {
                    "id": child_id,
                    "name": name,
                    "parent_id": str(child.get("parent_id") or department_id),
                    "depth": depth + 1,
                }
            )
            queue.append((child_id, depth + 1))

        cursor = 0
        for _page in range(1000):
            user_payload = _post_json(
                DEPARTMENT_USERS_URL,
                action="department member lookup",
                params=params,
                json={
                    "dept_id": int(department_id),
                    "cursor": cursor,
                    "size": 100,
                    "contain_access_limit": False,
                    "language": "zh_CN",
                },
            )
            result = user_payload.get("result") or {}
            for item in result.get("list") or []:
                user_id = str(item.get("userid") or "").strip()
                name = str(item.get("name") or "").strip()
                if not user_id or not name:
                    continue
                member = members.setdefault(
                    user_id,
                    {"user_id": user_id, "name": name, "department_ids": []},
                )
                if department_id not in member["department_ids"]:
                    member["department_ids"].append(department_id)
            if not result.get("has_more"):
                break
            next_cursor = result.get("next_cursor")
            if next_cursor is None or int(next_cursor) == cursor:
                raise DingTalkAuthError("DingTalk department member pagination did not advance")
            cursor = int(next_cursor)
        else:
            raise DingTalkAuthError("DingTalk department member pagination exceeded the safety limit")

    return {"departments": departments, "members": list(members.values())}


def profile_subject(profile: dict) -> str:
    return str(
        profile.get("unionId")
        or profile.get("unionid")
        or profile.get("openId")
        or profile.get("openid")
        or ""
    ).strip()


def profile_union_id(profile: dict) -> str:
    return str(profile.get("unionId") or profile.get("unionid") or "").strip()


def profile_open_id(profile: dict) -> str:
    return str(profile.get("openId") or profile.get("openid") or "").strip()


def profile_email(profile: dict) -> str:
    return str(profile.get("email") or profile.get("orgEmail") or "").strip().lower()


def profile_name(profile: dict) -> str:
    return str(profile.get("nick") or profile.get("name") or "DingTalk User").strip() or "DingTalk User"
