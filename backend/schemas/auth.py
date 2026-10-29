"""Учётки и вход (контракт docs/contracts/api.md, «Учётки и вход»). Менять только через техлида."""

from uuid import UUID

from pydantic import BaseModel, Field


class Credentials(BaseModel):
    login: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=128)


class Account(BaseModel):
    id: UUID  # тот же user_id, что у записей и разговоров учётки
    login: str
    demo: bool  # демо-учётка с датасетом


class AuthResponse(BaseModel):
    token: str  # клиент присылает его в `Authorization: Bearer <token>`
    account: Account
