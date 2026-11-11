"""
Shared test setup for CafeQuick (run from the repo root:  pytest Tests --cov=Backend).

What this file does:
  1. Puts the repo root and ../Database on sys.path (same trick as Backend/main.py).
  2. Gives every test its OWN empty SQLite file in a temp folder, so your real
     cafequick_test.db is never touched (do NOT call seed()/init_db() in tests: they wipe it).
  3. Freezes "now" inside Backend/main.py. Business rules depend on the clock
     (20-minute rule, 15-minute cancel window, 35-minute uncollected cutoff), and without a
     frozen clock the tests would pass or fail depending on the time of day you run them.
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "Database"))

from Backend import main                                   # the app under test
from cafequick_db import (User, Wallet, WalletTransaction, MenuItem, Order, OrderLine,
                          OrderState, Role, TxKind)

# A Monday, 07:00. The cafeteria window is 08:00-15:00, so slots at 10:00 etc. are valid.
START = datetime(2026, 11, 9, 7, 0)
CLOCK = {"now": START}                                     # tests change CLOCK["now"] to move time


class FakeDatetime(datetime):
    """Replaces `datetime` inside main.py. Only now() is changed; everything else is real."""
    @classmethod
    def now(cls, tz=None):
        return CLOCK["now"]


@pytest.fixture(autouse=True)
def isolated_app(tmp_path, monkeypatch):
    """Runs before every test: fresh DB file + frozen clock."""
    CLOCK["now"] = START
    eng = create_engine(f"sqlite:///{tmp_path / 'test.db'}",
                        connect_args={"check_same_thread": False, "timeout": 30})

    @event.listens_for(eng, "connect")
    def _fk_on(dbapi_conn, _):                             # make SQLite enforce foreign keys like PostgreSQL
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    SQLModel.metadata.create_all(eng)                      # CHECK constraints are created here too
    monkeypatch.setattr(main, "engine", eng)               # get_db() and the job read main.engine at call time
    monkeypatch.setattr(main, "datetime", FakeDatetime)    # freeze the clock used by the endpoints
    yield eng
    eng.dispose()


@pytest.fixture
def engine(isolated_app):
    return isolated_app


@pytest.fixture
def client():
    # No `with` block on purpose: it would start the APScheduler job from main.py.
    return TestClient(main.app)


# ----------------------------------------------------------------- helpers (plain functions)
def slot(hour, minute=0, day_offset=0):
    """A pickup slot on the frozen day, e.g. slot(10) = 10:00."""
    return START.replace(hour=hour, minute=minute) + timedelta(days=day_offset)


def make_user(engine, email, role=Role.customer, balance=0):
    """Create a user + wallet (+ one top-up ledger row so balance == sum(ledger))."""
    with Session(engine) as s:
        u = User(name=email.split("@")[0], email=email, role=role)
        s.add(u); s.commit(); s.refresh(u)
        w = Wallet(user_id=u.id, balance=balance)
        s.add(w); s.commit(); s.refresh(w)
        if balance:
            s.add(WalletTransaction(wallet_id=w.id, amount=balance, kind=TxKind.topup, reference="test"))
            s.commit()
        return u.id


def make_item(engine, name="Falafel", price=1000, stock=10, tags="vegan", available=True):
    with Session(engine) as s:
        i = MenuItem(name=name, price=price, stock=stock, tags=tags, available=available)
        s.add(i); s.commit(); s.refresh(i)
        return i.id


def add_order(engine, customer_id, slot_start, state, lines):
    """Insert an order straight into the DB. lines = [(item_id, quantity, unit_price), ...]"""
    with Session(engine) as s:
        o = Order(customer_id=customer_id, slot_start=slot_start, state=state, pickup_code="1234",
                  total=sum(q * p for _, q, p in lines))
        s.add(o); s.commit(); s.refresh(o)
        for item_id, q, p in lines:
            s.add(OrderLine(order_id=o.id, item_id=item_id, quantity=q, price=p))
        s.commit()
        return o.id


def get_row(engine, model, pk):
    with Session(engine) as s:
        return s.get(model, pk)


def balance_and_ledger(engine, user_id):
    """(cached balance, sum of ledger rows) for one user. They must always be equal."""
    with Session(engine) as s:
        w = s.query(Wallet).filter(Wallet.user_id == user_id).one()
        total = sum(t.amount for t in s.query(WalletTransaction).filter(WalletTransaction.wallet_id == w.id))
        return w.balance, total


def order_body(slot_start, *lines):
    """JSON body for POST /orders. lines = (item_id, quantity) pairs."""
    return {"slot_start": slot_start.isoformat(),
            "lines": [{"item_id": i, "quantity": q} for i, q in lines]}


def H(email):
    """Header that main.current_user() reads (simulated SSO)."""
    return {"X-User-Email": email}
