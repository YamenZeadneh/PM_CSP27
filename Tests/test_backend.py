"""
CafeQuick back-end tests (NFR-08). Each test names the requirement or objective it proves.
Run from the repo root:   pytest Tests --cov=Backend --cov-report=term-missing
Fixtures and helpers live in conftest.py.
"""
import threading
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from Backend import main
from cafequick_db import (MenuItem, Order, OrderState, Role, Strike, User, Wallet, WalletTransaction)
from conftest import (CLOCK, H, START, add_order, balance_and_ledger, get_row, make_item,
                      make_user, order_body, slot)


# ======================================================================= auth / roles (FR-01, NFR-03)
def test_missing_or_unknown_user_is_401(client):
    assert client.get("/menu").status_code == 401
    assert client.get("/menu", headers=H("nobody@uni.edu")).status_code == 401


def test_role_is_enforced_403(engine, client):
    make_user(engine, "c@uni.edu", Role.customer)
    assert client.get("/kitchen/queue", headers=H("c@uni.edu")).status_code == 403
    assert client.get("/audit", headers=H("c@uni.edu")).status_code == 403
    assert client.get("/reports/daily", headers=H("c@uni.edu")).status_code == 403


# ======================================================================= menu (FR-02, FR-14)
def test_customer_sees_only_available_in_stock_items_with_tags(engine, client):
    make_user(engine, "c@uni.edu")
    make_user(engine, "m@uni.edu", Role.manager)
    make_item(engine, "Visible", stock=5, tags="vegan,gluten")
    make_item(engine, "SoldOut", stock=0)
    make_item(engine, "Withdrawn", stock=5, available=False)
    cust = client.get("/menu", headers=H("c@uni.edu")).json()
    assert [i["name"] for i in cust] == ["Visible"]
    assert cust[0]["tags"] == "vegan,gluten"                           # FR-14
    assert len(client.get("/menu", headers=H("m@uni.edu")).json()) == 3  # manager sees all


# ======================================================================= ordering rules (FR-03, FR-04, FR-10)
def test_order_happy_path_pays_reserves_stock_and_writes_ledger(engine, client):
    uid = make_user(engine, "c@uni.edu", balance=5000)
    item = make_item(engine, price=1000, stock=10)
    r = client.post("/orders", json=order_body(slot(10), (item, 2)), headers=H("c@uni.edu"))
    assert r.status_code == 201 and r.json()["total"] == 2000
    assert get_row(engine, MenuItem, item).stock == 8                  # FR-10
    bal, ledger = balance_and_ledger(engine, uid)
    assert bal == ledger == 3000                                       # FR-04 + ledger rule


@pytest.mark.parametrize("hour,minute", [(10, 10), (7, 45), (15, 0)])
def test_invalid_slot_is_422(engine, client, hour, minute):
    make_user(engine, "c@uni.edu", balance=5000)
    item = make_item(engine)
    r = client.post("/orders", json=order_body(slot(hour, minute), (item, 1)), headers=H("c@uni.edu"))
    assert r.status_code == 422                                        # not on 15 min grid / outside 08-15


def test_slot_less_than_20_minutes_ahead_is_422(engine, client):
    make_user(engine, "c@uni.edu", balance=5000)
    item = make_item(engine)
    CLOCK["now"] = slot(10, 0)
    assert client.post("/orders", json=order_body(slot(10, 15), (item, 1)),
                       headers=H("c@uni.edu")).status_code == 422      # 15 min ahead
    assert client.post("/orders", json=order_body(slot(10, 30), (item, 1)),
                       headers=H("c@uni.edu")).status_code == 201      # 30 min ahead


def test_more_than_5_lines_rejected(engine, client):
    make_user(engine, "c@uni.edu", balance=50000)
    ids = [make_item(engine, f"i{n}") for n in range(6)]
    r = client.post("/orders", json=order_body(slot(10), *[(i, 1) for i in ids]), headers=H("c@uni.edu"))
    assert r.status_code == 422                                        # FR-03: 1-5 items


def test_slot_capacity_is_20_objective2(engine, client):
    item = make_item(engine, stock=100)
    for n in range(21):
        make_user(engine, f"s{n}@uni.edu", balance=5000)
    codes = [client.post("/orders", json=order_body(slot(10), (item, 1)),
                         headers=H(f"s{n}@uni.edu")).status_code for n in range(21)]
    assert codes == [201] * 20 + [409]                                 # 21st refused
    with Session(engine) as s:
        assert s.query(Order).count() == 20


def test_one_order_per_customer_per_slot(engine, client):
    make_user(engine, "c@uni.edu", balance=5000)
    item = make_item(engine)
    assert client.post("/orders", json=order_body(slot(10), (item, 1)), headers=H("c@uni.edu")).status_code == 201
    assert client.post("/orders", json=order_body(slot(10), (item, 1)), headers=H("c@uni.edu")).status_code == 409
    assert client.post("/orders", json=order_body(slot(10, 15), (item, 1)), headers=H("c@uni.edu")).status_code == 201


def test_stock_is_never_oversold_objective2(engine, client):
    make_user(engine, "a@uni.edu", balance=5000)
    make_user(engine, "b@uni.edu", balance=5000)
    item = make_item(engine, stock=1)
    assert client.post("/orders", json=order_body(slot(10), (item, 1)), headers=H("a@uni.edu")).status_code == 201
    assert client.post("/orders", json=order_body(slot(10), (item, 1)), headers=H("b@uni.edu")).status_code == 409
    assert get_row(engine, MenuItem, item).stock == 0


def test_wallet_never_below_zero_and_failed_order_rolls_back_objective2(engine, client):
    uid = make_user(engine, "c@uni.edu", balance=500)
    cheap = make_item(engine, "cheap", price=100, stock=5)
    dear = make_item(engine, "dear", price=1000, stock=5)
    r = client.post("/orders", json=order_body(slot(10), (cheap, 1), (dear, 1)), headers=H("c@uni.edu"))
    assert r.status_code == 402
    assert balance_and_ledger(engine, uid) == (500, 500)               # nothing charged
    assert get_row(engine, MenuItem, cheap).stock == 5                 # stock reservation rolled back
    with Session(engine) as s:
        assert s.query(Order).count() == 0


def test_withdrawn_item_cannot_be_ordered(engine, client):
    make_user(engine, "c@uni.edu", balance=5000)
    item = make_item(engine, available=False)
    assert client.post("/orders", json=order_body(slot(10), (item, 1)), headers=H("c@uni.edu")).status_code == 409


def test_blocked_customer_cannot_order_fr09(engine, client):
    uid = make_user(engine, "c@uni.edu", balance=5000)
    item = make_item(engine)
    with Session(engine) as s:
        u = s.get(User, uid); u.blocked_until = START + timedelta(days=1); s.add(u); s.commit()
    assert client.post("/orders", json=order_body(slot(10), (item, 1)), headers=H("c@uni.edu")).status_code == 403


def test_slots_endpoint_counts_taken(engine, client):
    make_user(engine, "c@uni.edu", balance=5000)
    item = make_item(engine)
    client.post("/orders", json=order_body(slot(10), (item, 1)), headers=H("c@uni.edu"))
    rows = {r["slot_start"]: r for r in client.get("/slots", headers=H("c@uni.edu")).json()}
    s10 = rows[slot(10).isoformat()]
    assert (s10["taken"], s10["remaining"], s10["bookable"]) == (1, 19, True)
    assert len(rows) == 28                                             # 08:00..14:45 in 15 min steps


# ======================================================================= cancellation (FR-05)
def _place(client, email, item, when=None, qty=1):
    r = client.post("/orders", json=order_body(when or slot(10), (item, qty)), headers=H(email))
    assert r.status_code == 201, r.text
    return r.json()["order_id"]


def test_cancel_before_window_refunds_and_restores_stock(engine, client):
    uid = make_user(engine, "c@uni.edu", balance=5000)
    item = make_item(engine, price=1000, stock=10)
    oid = _place(client, "c@uni.edu", item, qty=2)
    CLOCK["now"] = slot(9, 45)                                         # 15 min before 10:00 = still allowed
    r = client.post(f"/orders/{oid}/cancel", headers=H("c@uni.edu"))
    assert r.status_code == 200 and r.json()["refunded"] == 2000
    assert get_row(engine, MenuItem, item).stock == 10
    assert balance_and_ledger(engine, uid) == (5000, 5000)
    assert get_row(engine, Order, oid).state == OrderState.cancelled


def test_cancel_after_window_is_409(engine, client):
    make_user(engine, "c@uni.edu", balance=5000)
    oid = _place(client, "c@uni.edu", make_item(engine))
    CLOCK["now"] = slot(9, 46)                                         # 14 min before the slot
    assert client.post(f"/orders/{oid}/cancel", headers=H("c@uni.edu")).status_code == 409


def test_cancelled_order_frees_the_slot(engine, client):
    item = make_item(engine, stock=100)
    for n in range(21):
        make_user(engine, f"s{n}@uni.edu", balance=5000)
    ids = [_place(client, f"s{n}@uni.edu", item) for n in range(20)]
    assert client.post("/orders", json=order_body(slot(10), (item, 1)), headers=H("s20@uni.edu")).status_code == 409
    client.post(f"/orders/{ids[0]}/cancel", headers=H("s0@uni.edu"))
    assert client.post("/orders", json=order_body(slot(10), (item, 1)), headers=H("s20@uni.edu")).status_code == 201


def test_cancel_rules_owner_and_state(engine, client):
    make_user(engine, "a@uni.edu", balance=5000)
    make_user(engine, "b@uni.edu", balance=5000)
    make_user(engine, "k@uni.edu", Role.kitchen)
    oid = _place(client, "a@uni.edu", make_item(engine))
    assert client.post(f"/orders/{oid}/cancel", headers=H("b@uni.edu")).status_code == 403   # not yours
    assert client.post("/orders/999/cancel", headers=H("a@uni.edu")).status_code == 404
    client.post(f"/orders/{oid}/preparing", headers=H("k@uni.edu"))
    assert client.post(f"/orders/{oid}/cancel", headers=H("a@uni.edu")).status_code == 409   # kitchen started


# ======================================================================= kitchen + pickup (FR-06, FR-07)
def test_kitchen_flow_and_pickup_code(engine, client):
    make_user(engine, "c@uni.edu", balance=5000)
    make_user(engine, "k@uni.edu", Role.kitchen)
    make_user(engine, "cash@uni.edu", Role.cashier)
    oid = _place(client, "c@uni.edu", make_item(engine))

    q = client.get("/kitchen/queue", headers=H("k@uni.edu")).json()
    assert len(q) == 1 and "pickup_code" not in q[0]                   # kitchen never sees the code
    assert client.post(f"/orders/{oid}/ready", headers=H("k@uni.edu")).status_code == 409    # must prepare first
    assert client.post(f"/orders/{oid}/preparing", headers=H("k@uni.edu")).status_code == 200
    assert client.get("/orders/mine", headers=H("c@uni.edu")).json()[0]["pickup_code"] is None
    assert client.post(f"/orders/{oid}/ready", headers=H("k@uni.edu")).status_code == 200

    code = client.get("/orders/mine", headers=H("c@uni.edu")).json()[0]["pickup_code"]
    assert code and len(code) == 4                                     # revealed only when ready
    wrong = "0000" if code != "0000" else "1111"
    assert client.post(f"/orders/{oid}/pickup", json={"code": wrong}, headers=H("cash@uni.edu")).status_code == 403
    assert client.post(f"/orders/{oid}/pickup", json={"code": "12"}, headers=H("cash@uni.edu")).status_code == 422
    assert client.post(f"/orders/{oid}/pickup", json={"code": code}, headers=H("k@uni.edu")).status_code == 403
    assert client.post(f"/orders/{oid}/pickup", json={"code": code}, headers=H("cash@uni.edu")).status_code == 200
    assert get_row(engine, Order, oid).state == OrderState.collected
    assert client.post(f"/orders/{oid}/pickup", json={"code": code}, headers=H("cash@uni.edu")).status_code == 409


def test_kitchen_404_for_unknown_order(engine, client):
    make_user(engine, "k@uni.edu", Role.kitchen)
    assert client.post("/orders/999/preparing", headers=H("k@uni.edu")).status_code == 404


# ======================================================================= top-up (FR-13)
def test_topup_adds_ledger_row_and_balance(engine, client):
    uid = make_user(engine, "c@uni.edu", balance=0)
    make_user(engine, "cash@uni.edu", Role.cashier)
    r = client.post("/wallet/topup", json={"customer_email": "c@uni.edu", "amount": 2500}, headers=H("cash@uni.edu"))
    assert r.status_code == 201 and r.json()["balance"] == 2500
    assert balance_and_ledger(engine, uid) == (2500, 2500)
    assert client.post("/wallet/topup", json={"customer_email": "x@uni.edu", "amount": 5},
                       headers=H("cash@uni.edu")).status_code == 404
    assert client.post("/wallet/topup", json={"customer_email": "c@uni.edu", "amount": 0},
                       headers=H("cash@uni.edu")).status_code == 422   # must be positive


# ======================================================================= uncollected job (FR-08, FR-09, objective 3)
def test_uncollected_orders_get_strike_no_refund_and_three_strikes_block(engine):
    uid = make_user(engine, "c@uni.edu", balance=0)
    item = make_item(engine)
    # slot ended > 20 min ago means slot_start < now - 35 min
    for n in range(3):
        add_order(engine, uid, START - timedelta(minutes=40 + 15 * n), OrderState.ready, [(item, 1, 1000)])
    # inside the grace period (slot_start = now - 30 min) -> must NOT be marked yet
    add_order(engine, uid, START - timedelta(minutes=30), OrderState.ready, [(item, 1, 1000)])
    # not ready (still preparing) -> never uncollected
    add_order(engine, uid, START - timedelta(minutes=120), OrderState.preparing, [(item, 1, 1000)])

    assert main.mark_uncollected_orders() == 3
    with Session(engine) as s:
        assert s.query(Strike).count() == 3
        assert s.query(Order).filter(Order.state == OrderState.uncollected).count() == 3
        assert s.get(User, uid).blocked_until == START + timedelta(days=7)      # FR-09
        assert s.query(WalletTransaction).count() == 0                           # no refund (FR-08)
    assert main.mark_uncollected_orders() == 0                                   # idempotent: second run does nothing


def test_two_strikes_do_not_block(engine):
    uid = make_user(engine, "c@uni.edu")
    item = make_item(engine)
    for n in range(2):
        add_order(engine, uid, START - timedelta(minutes=40 + 15 * n), OrderState.ready, [(item, 1, 1000)])
    main.mark_uncollected_orders()
    assert get_row(engine, User, uid).blocked_until is None


def test_old_strikes_outside_30_days_do_not_count(engine):
    uid = make_user(engine, "c@uni.edu")
    item = make_item(engine)
    old = [add_order(engine, uid, START - timedelta(days=40 + n), OrderState.uncollected, [(item, 1, 1000)])
           for n in range(2)]
    with Session(engine) as s:
        for oid in old:
            s.add(Strike(user_id=uid, order_id=oid, time=START - timedelta(days=40)))
        s.commit()
    add_order(engine, uid, START - timedelta(minutes=40), OrderState.ready, [(item, 1, 1000)])
    main.mark_uncollected_orders()                                   # 1 recent + 2 old = only 1 counts
    assert get_row(engine, User, uid).blocked_until is None


def test_admin_can_trigger_job_by_hand(engine, client):
    make_user(engine, "a@uni.edu", Role.admin)
    make_user(engine, "c@uni.edu")
    assert client.post("/admin/run-uncollected-job", headers=H("a@uni.edu")).json() == {"marked_uncollected": 0}
    assert client.post("/admin/run-uncollected-job", headers=H("c@uni.edu")).status_code == 403


# ======================================================================= withdrawal (FR-12)
def test_withdrawal_refunds_only_orders_not_yet_prepared(engine, client):
    a = make_user(engine, "a@uni.edu", balance=5000)
    b = make_user(engine, "b@uni.edu", balance=5000)
    c = make_user(engine, "c@uni.edu", balance=5000)
    make_user(engine, "k@uni.edu", Role.kitchen)
    item1 = make_item(engine, "withdrawn", price=1000, stock=10)
    item2 = make_item(engine, "other", price=500, stock=10)
    oa = _place(client, "a@uni.edu", item1, qty=2)                    # placed   -> refunded
    ob = _place(client, "b@uni.edu", item1, qty=1)                    # preparing -> kept
    oc = _place(client, "c@uni.edu", item2, qty=1)                    # other item -> untouched
    client.post(f"/orders/{ob}/preparing", headers=H("k@uni.edu"))

    r = client.post(f"/menu/{item1}/withdraw", headers=H("k@uni.edu"))
    assert r.status_code == 200 and r.json()["cancelled_orders"] == [oa]
    assert get_row(engine, Order, oa).state == OrderState.cancelled
    assert get_row(engine, Order, ob).state == OrderState.preparing
    assert get_row(engine, Order, oc).state == OrderState.placed
    assert balance_and_ledger(engine, a) == (5000, 5000)              # full refund
    assert balance_and_ledger(engine, b) == (4000, 4000)
    assert get_row(engine, MenuItem, item1).available is False
    assert get_row(engine, MenuItem, item1).stock == 9               # 10 - 2 - 1 + 2 restored for A
    assert client.post("/orders", json=order_body(slot(11), (item1, 1)), headers=H("c@uni.edu")).status_code == 409


def test_withdrawal_role_and_404(engine, client):
    make_user(engine, "c@uni.edu")
    make_user(engine, "k@uni.edu", Role.kitchen)
    item = make_item(engine)
    assert client.post(f"/menu/{item}/withdraw", headers=H("c@uni.edu")).status_code == 403
    assert client.post("/menu/999/withdraw", headers=H("k@uni.edu")).status_code == 404


# ======================================================================= manager menu endpoints (FR-02)
def test_manager_menu_crud(engine, client):
    make_user(engine, "m@uni.edu", Role.manager)
    r = client.post("/menu", json={"name": "Tea", "price": 300, "stock": 5, "tags": "vegan"}, headers=H("m@uni.edu"))
    assert r.status_code == 201
    iid = r.json()["id"]
    assert client.put(f"/menu/{iid}", json={"price": 400, "name": "Tea+"}, headers=H("m@uni.edu")).json()["price"] == 400
    assert client.put(f"/menu/{iid}/stock", json={"stock": 9}, headers=H("m@uni.edu")).json()["stock"] == 9
    assert client.put("/menu/999", json={"price": 1}, headers=H("m@uni.edu")).status_code == 404
    assert client.put("/menu/999/stock", json={"stock": 1}, headers=H("m@uni.edu")).status_code == 404
    assert client.put(f"/menu/{iid}/stock", json={"stock": -1}, headers=H("m@uni.edu")).status_code == 422


# ======================================================================= daily report (FR-11, objective 4)
def test_daily_report_numbers(engine, client):
    make_user(engine, "m@uni.edu", Role.manager)
    u1, u2, u3, u4 = (make_user(engine, f"u{n}@uni.edu") for n in range(4))
    shawarma = make_item(engine, "Shawarma", price=2500)
    falafel = make_item(engine, "Falafel", price=1000)
    coffee = make_item(engine, "Coffee", price=600)
    tea = make_item(engine, "Tea", price=300)
    add_order(engine, u1, slot(9), OrderState.collected, [(shawarma, 2, 2500), (coffee, 1, 600)])   # 5600
    add_order(engine, u2, slot(9), OrderState.uncollected, [(falafel, 3, 1000)])                    # 3000
    add_order(engine, u3, slot(10), OrderState.cancelled, [(tea, 5, 300)])                          # refunded
    add_order(engine, u4, slot(10), OrderState.placed, [(falafel, 1, 1000)])                        # not final
    add_order(engine, u1, slot(10, 15, day_offset=1), OrderState.collected, [(tea, 1, 300)])        # other day

    r = client.get(f"/reports/daily?day={START.date().isoformat()}", headers=H("m@uni.edu"))
    assert r.status_code == 200
    d = r.json()
    assert (d["orders"], d["collected"], d["uncollected"], d["cancelled"]) == (4, 1, 1, 1)
    assert d["revenue"] == 5600 + 3000
    # falafel 3+1=4, shawarma 2, coffee 1; cancelled tea (5) is excluded
    assert d["top_items"] == [{"name": "Falafel", "quantity": 4},
                              {"name": "Shawarma", "quantity": 2},
                              {"name": "Coffee", "quantity": 1}]


def test_daily_report_empty_day_defaults_to_today(engine, client):
    make_user(engine, "m@uni.edu", Role.manager)
    d = client.get("/reports/daily", headers=H("m@uni.edu")).json()
    assert d["day"] == START.date().isoformat()
    assert (d["orders"], d["revenue"], d["top_items"]) == (0, 0, [])


# ======================================================================= audit log (FR-16)
def test_audit_log_records_actions_and_is_admin_only(engine, client):
    make_user(engine, "a@uni.edu", Role.admin)
    make_user(engine, "c@uni.edu", balance=5000)
    make_user(engine, "k@uni.edu", Role.kitchen)
    oid = _place(client, "c@uni.edu", make_item(engine))
    client.post(f"/orders/{oid}/preparing", headers=H("k@uni.edu"))

    log = client.get("/audit", headers=H("a@uni.edu")).json()
    assert [e["action"] for e in log] == ["ORDER_PREPARING", "ORDER_PLACED"]       # newest first
    assert all(e["target"] == f"order:{oid}" for e in log)
    only = client.get("/audit?action=ORDER_PLACED", headers=H("a@uni.edu")).json()
    assert len(only) == 1
    assert len(client.get("/audit?limit=1", headers=H("a@uni.edu")).json()) == 1
    assert client.get("/audit?limit=0", headers=H("a@uni.edu")).status_code == 422
    assert client.get("/audit", headers=H("k@uni.edu")).status_code == 403


# ======================================================================= concurrency (objective 2, NFR-01)
def test_concurrent_orders_keep_invariants(engine):
    """30 customers hit the SAME slot and the SAME scarce item at once.
    Whatever the individual status codes are, these must hold afterwards:
      slot <= 20 orders, stock >= 0 and consistent, wallets >= 0, ledger == balance.
    NOTE: SQLite has no row locks (with_for_update is ignored), so this test is only a smoke test.
    The real proof needs PostgreSQL + the advisory lock mentioned in place_order."""
    item = make_item(engine, price=1000, stock=25)
    users = [make_user(engine, f"s{n}@uni.edu", balance=3000) for n in range(30)]
    results = []

    def worker(n):
        c = TestClient(main.app, raise_server_exceptions=False)    # one client per thread
        r = c.post("/orders", json=order_body(slot(10), (item, 1)), headers=H(f"s{n}@uni.edu"))
        results.append(r.status_code)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(30)]
    [t.start() for t in threads]
    [t.join() for t in threads]

    ok = results.count(201)
    with Session(engine) as s:
        orders = s.query(Order).count()
        stock = s.get(MenuItem, item).stock
    assert orders == ok and 1 <= ok <= 20                           # slot never overfilled
    assert stock == 25 - ok and stock >= 0                          # stock matches accepted orders
    for uid in users:
        bal, ledger = balance_and_ledger(engine, uid)
        assert bal == ledger and bal >= 0
