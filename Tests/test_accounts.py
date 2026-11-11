"""
Account tests (FR-01, FR-04, NFR-03, NFR-08). Same style as test_backend.py; fixtures are in conftest.py.
Needs the two lines from Backend/accounts.py added at the end of Backend/main.py.
"""
from sqlmodel import Session

from Backend import accounts
from cafequick_db import AuditEntry, Role, User
from conftest import H, balance_and_ledger, make_user


def _signup(client, email="new@uni.edu", balance=10000, name="New Student"):
    return client.post("/signup", json={"name": name, "email": email, "initial_balance": balance})


def test_signup_creates_customer_wallet_and_ledger_row(engine, client):
    r = _signup(client, email="New@Uni.edu", balance=10000)
    assert r.status_code == 201 and r.json()["email"] == "new@uni.edu"       # e-mail is lower-cased
    me = client.get("/me", headers=H("new@uni.edu")).json()
    assert (me["role"], me["balance"]) == ("customer", 10000)
    assert balance_and_ledger(engine, me["id"]) == (10000, 10000)             # balance == ledger from day one
    with Session(engine) as s:
        assert s.query(AuditEntry).filter(AuditEntry.action == "ACCOUNT_CREATED").count() == 1


def test_signup_with_zero_balance_has_no_ledger_row(engine, client):
    assert _signup(client, balance=0).status_code == 201
    uid = client.get("/me", headers=H("new@uni.edu")).json()["id"]
    assert balance_and_ledger(engine, uid) == (0, 0)


def test_signup_rejects_duplicate_bad_email_and_huge_balance(engine, client):
    make_user(engine, "taken@uni.edu")
    assert _signup(client, email="taken@uni.edu").status_code == 409
    assert _signup(client, email="   ").status_code == 422                   # empty is refused
    assert _signup(client, email="yamin@just").status_code == 201            # fake e-mails are fine (demo)
    assert _signup(client, balance=accounts.MAX_SIGNUP_BALANCE + 1).status_code == 422
    assert client.post("/signup", json={"name": "x", "email": "a@b.co", "initial_balance": -5}).status_code == 422


def test_signup_cannot_choose_a_role(engine, client):
    r = client.post("/signup", json={"name": "Evil", "email": "evil@uni.edu", "role": "admin"})
    assert r.status_code == 201
    assert client.get("/me", headers=H("evil@uni.edu")).json()["role"] == "customer"   # extra field ignored


def test_self_funding_switch(engine, client, monkeypatch):
    monkeypatch.setattr(accounts, "ALLOW_SELF_FUNDING", False)
    assert _signup(client, balance=5000).status_code == 403
    assert _signup(client, balance=0).status_code == 201


def test_me_and_wallet_history(engine, client):
    make_user(engine, "k@uni.edu", Role.kitchen)
    assert client.get("/me").status_code == 401
    assert client.get("/me", headers=H("k@uni.edu")).json()["role"] == "kitchen"
    _signup(client, balance=2500)
    hist = client.get("/wallet/history", headers=H("new@uni.edu")).json()
    assert hist["balance"] == 2500
    assert [(t["kind"], t["amount"], t["reference"]) for t in hist["transactions"]] == [("topup", 2500, "signup")]
