"""Поддельный Google для тестов календаря (calendar-01): OAuth и Calendar API в памяти.

Подключается через `monkeypatch.setattr(google, "http_client", fake.client)` — сети нет.
"""

import base64
import json
from urllib.parse import unquote

import httpx


class FakeGoogle:
    """Что получил «Google», что в нём лежит и что он ответит."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.token_status = 200
        self.token_error = "invalid_grant"
        self.refresh_token: str | None = "1//refresh"
        self.scopes = ["https://www.googleapis.com/auth/calendar.app.created", "openid",
                       "https://www.googleapis.com/auth/userinfo.email"]  # что «разрешил» человек
        self.scope_in_token = True  # кладёт ли Google `scope` в ответ с токенами
        self.calendars: list[str] = []
        self.events: dict[str, dict] = {}  # id события → тело (status = cancelled — удалено)
        self.down = False  # Google не отвечает (таймаут, сеть)

    def client(self, timeout=None) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.down:
            raise httpx.ConnectTimeout("Google не отвечает", request=request)
        path = unquote(request.url.path)
        if path == "/token":
            return self._token()
        if path == "/revoke":
            return httpx.Response(200)
        if path == "/calendar/v3/calendars":
            if "https://www.googleapis.com/auth/calendar.app.created" not in self.scopes:
                return httpx.Response(403, json={"error": {"code": 403}})
            calendar_id = f"cal{len(self.calendars) + 1}@group.calendar.google.com"
            self.calendars.append(calendar_id)
            return httpx.Response(200, json={"id": calendar_id})
        return self._events(request, path)

    def _token(self) -> httpx.Response:
        if self.token_status != 200:
            return httpx.Response(self.token_status, json={"error": self.token_error})
        claims = base64.urlsafe_b64encode(json.dumps({"email": "anna@gmail.com"}).encode())
        body = {"access_token": "ya29.access", "id_token": f"h.{claims.decode()}.s"}
        if self.scope_in_token:
            body["scope"] = " ".join(self.scopes)
        if self.refresh_token:
            body["refresh_token"] = self.refresh_token
        return httpx.Response(200, json=body)

    def _events(self, request: httpx.Request, path: str) -> httpx.Response:
        parts = path.removeprefix("/calendar/v3/calendars/").split("/")
        calendar_id, event_id = parts[0], parts[2] if len(parts) > 2 else None
        if calendar_id not in self.calendars:
            return httpx.Response(404)
        if request.method == "POST":
            body = json.loads(request.content)
            if body["id"] in self.events:
                return httpx.Response(409)
            self.events[body["id"]] = body
            return httpx.Response(200, json=body)
        if request.method == "PUT":
            if event_id not in self.events:
                return httpx.Response(404)
            self.events[event_id] = json.loads(request.content)
            return httpx.Response(200, json=self.events[event_id])
        if request.method == "DELETE":
            if event_id not in self.events or self.events[event_id]["status"] == "cancelled":
                return httpx.Response(410)
            self.events[event_id]["status"] = "cancelled"
            return httpx.Response(204)
        return httpx.Response(405)

    def paths(self) -> list[str]:
        return [unquote(r.url.path) for r in self.requests]

    def live(self) -> dict[str, dict]:
        """События, которые видит пользователь в Google (не удалённые)."""
        return {i: e for i, e in self.events.items() if e["status"] != "cancelled"}
