import secrets
import sys
from datetime import datetime, timedelta, date          # NEW: date is used by GET /slots
from pathlib import Path
from typing import Optional                              # NEW: optional query/body fields
from fastapi import FastAPI, Depends, HTTPException, Header
from pydantic import BaseModel, Field
from sqlalchemy import select, func      # FIX: one import, "select" was imported twice
from sqlalchemy.orm import Session
from apscheduler.schedulers.background import BackgroundScheduler   # NEW: runs the uncollected job (pip install apscheduler)

# FIX: add the ../Database folder to Python's import path so "cafequick_db" can be found
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "Database"))

# FIX: import the module by name (cafequick_db), not by file path; engine and User added for get_db/current_user
# NEW: Role (for the role check) and Strike (for the uncollected job) added to the import
from cafequick_db import (engine, User, MenuItem, Wallet, WalletTransaction, Order, OrderLine,
                          OrderState, TxKind, AuditEntry, Role, Strike)
app = FastAPI()

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5500", "http://localhost:5500"],  # the frontend's origin
    allow_methods=["*"],
    allow_headers=["*"],   # lets the custom X-User-Email header through
)

class LineIn(BaseModel):
    item_id: int
    quantity: int = Field(ge=1)

class OrderIn(BaseModel):
    slot_start: datetime
    lines: list[LineIn] = Field(min_length=1, max_length=5)


# FIX for the red underline in your screenshot: cafequick_db.py lives in ../Database,
# so Python can't find it. Add that folder to the import path BEFORE the cafequick_db import.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "Database"))
from cafequick_db import engine, User           # engine and User are added to your existing import


def get_db():
    # One session per request. FastAPI runs the code after `yield` when the request ends,
    # so the session is always closed, even if the endpoint raised an error.
    # expire_on_commit=False: after current_user commits (see below), the loaded `user`
    # keeps its attributes instead of being refreshed, which would start a new transaction.
    db = Session(engine, expire_on_commit=False)
    try:
        yield db
    finally:
        db.close()


def current_user(x_user_email: str = Header(None), db: Session = Depends(get_db)):
    # Simulated SSO: the caller says who they are via the X-User-Email header.
    if not x_user_email:
        raise HTTPException(401, "Missing X-User-Email header")
    user = db.scalar(select(User).where(User.email == x_user_email))
    if not user:
        raise HTTPException(401, "Unknown user")
    # IMPORTANT: this SELECT auto-starts a transaction on the shared session. place_order
    # later calls `with db.begin()`, which errors if one is already open. Commit here to
    # close the read-only transaction (FastAPI reuses the same db for both dependencies).
    db.commit()
    return user


# ======================================================================================
# NEW (FR-01 / NFR-03): role check dependency.
# Usage:  user=Depends(require_role(Role.kitchen))
# It builds on current_user, so the 401 checks still run first; this only adds the 403.
# ======================================================================================
def require_role(*roles: Role):
    def checker(user=Depends(current_user)):
        if user.role not in roles:
            raise HTTPException(403, "Your role is not allowed to do this")
        return user
    return checker


# NEW (FR-16): one-line helper so every endpoint writes its audit row the same way.
# Must be called INSIDE a `with db.begin()` block so the audit row commits with the action.
def _audit(db: Session, actor_id: int, action: str, target: str):
    db.add(AuditEntry(actor_id=actor_id, action=action, target=target))


@app.post("/orders", status_code=201)
# CHANGED: was Depends(current_user); now only customers can place orders (FR-01)
def place_order(body: OrderIn, user=Depends(require_role(Role.customer)), db: Session = Depends(get_db)):
    if body.slot_start < datetime.now() + timedelta(minutes=20):
        raise HTTPException(422, "Slot starts in less than 20 minutes")

    # NEW (FR-03): slot must be on a 15-minute boundary and inside 08:00-15:00
    s = body.slot_start
    if s.minute % 15 != 0 or s.second != 0 or not (8 <= s.hour < 15):
        raise HTTPException(422, "Invalid pickup slot")

    # NEW (FR-09): blocked customers cannot order
    if user.blocked_until and user.blocked_until > datetime.now():
        raise HTTPException(403, "Ordering is blocked until " + user.blocked_until.isoformat())

    with db.begin():  # one transaction: all checks and writes commit or roll back together
        # (raising HTTPException inside this block rolls everything back automatically)

        # 1. Slot capacity (max 20) and one order per customer per slot
        # Cancelled orders do not occupy a slot, so they are excluded from both counts.
        # NOTE: two requests can both read "19" at the same time. On PostgreSQL, uncomment
        # the next line to serialize requests per slot (see notes below the code):
        # db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": int(s.timestamp())})  # needs: from sqlalchemy import text
        slot_count = db.scalar(
            select(func.count(Order.id)).where(
                Order.slot_start == s, Order.state != OrderState.cancelled))
        if slot_count >= 20:
            raise HTTPException(409, "Slot is full")
        already = db.scalar(                                  # NEW: customer already has an order here?
            select(func.count(Order.id)).where(
                Order.customer_id == user.id, Order.slot_start == s,
                Order.state != OrderState.cancelled))
        if already:
            raise HTTPException(409, "You already have an order in this slot")

        # 2. Lock item rows, check stock, decrement it
        total = 0
        order_lines = []  # NEW: remember (item, quantity) so we can build OrderLines in step 4
        # FIX: iterate in item_id order so two concurrent orders lock rows in the same order
        # (different order = possible deadlock)
        for l in sorted(body.lines, key=lambda x: x.item_id):
            item = db.scalar(select(MenuItem).where(MenuItem.id == l.item_id).with_for_update())
            # FIX: also reject items the kitchen withdrew (item.available is False)
            if not item or not item.available or item.stock < l.quantity:
                raise HTTPException(409, f"Item {l.item_id} unavailable")
            item.stock -= l.quantity                          # FR-10: reserve stock now
            total += item.price * l.quantity   # use integer fils, not float
            order_lines.append((item, l.quantity))

        # 3. Lock wallet row, check balance, write a ledger row
        wallet = db.scalar(select(Wallet).where(Wallet.user_id == user.id).with_for_update())
        if wallet.balance < total:
            raise HTTPException(402, "Insufficient balance")
        wallet.balance -= total
        # FIX: my WalletTransaction has wallet_id (not user_id) and kind is the TxKind enum;
        # the reference is filled after the order id exists (step 4)
        tx = WalletTransaction(wallet_id=wallet.id, amount=-total, kind=TxKind.payment)
        db.add(tx)

        # 4. Create Order + OrderLines with a 4-digit pickup code
        order = Order(
            customer_id=user.id,
            slot_start=s,
            state=OrderState.placed,
            total=total,
            pickup_code=f"{secrets.randbelow(10000):04d}",    # "0000".."9999", keeps leading zeros
        )
        db.add(order)
        db.flush()                                            # NEW: runs the INSERT so order.id exists

        for item, qty in order_lines:
            db.add(OrderLine(order_id=order.id, item_id=item.id,
                             quantity=qty, price=item.price))  # price snapshot at order time
        tx.reference = f"order:{order.id}"                    # link ledger row to the order
        db.add(AuditEntry(actor_id=user.id, action="ORDER_PLACED", target=f"order:{order.id}"))  # FR-16

    # NEW: return something useful (the code is shown to the customer when the order is ready)
    return {"status": "placed", "order_id": order.id, "total": total}


# ======================================================================================
# FR-02 / FR-14: MENU
# ======================================================================================
class MenuItemIn(BaseModel):                       # body for creating an item (manager)
    name: str = Field(min_length=1)
    price: int = Field(ge=0)                       # fils (1 JD = 1000 fils)
    stock: int = Field(ge=0)
    tags: str = ""                                 # comma separated dietary/allergen tags

class MenuItemUpdate(BaseModel):                   # body for editing name/price/tags (all optional)
    name: Optional[str] = Field(default=None, min_length=1)
    price: Optional[int] = Field(default=None, ge=0)
    tags: Optional[str] = None

class StockIn(BaseModel):                          # body for setting today's stock
    stock: int = Field(ge=0)


def _menu_dict(i: MenuItem):
    # Tags are included so the UI can show dietary/allergen info (FR-14)
    return {"id": i.id, "name": i.name, "price": i.price, "stock": i.stock,
            "tags": i.tags, "available": i.available}


@app.get("/menu")
def get_menu(user=Depends(current_user), db: Session = Depends(get_db)):
    # Customers only see items that can actually be ordered (FR-02).
    # Staff roles that manage the menu see everything, so the manager can fix stock of hidden items.
    q = select(MenuItem)
    if user.role not in (Role.manager, Role.admin, Role.kitchen):
        q = q.where(MenuItem.available == True, MenuItem.stock > 0)   # noqa: E712 (SQL needs == True)
    return [_menu_dict(i) for i in db.scalars(q.order_by(MenuItem.id)).all()]


@app.post("/menu", status_code=201)
def create_menu_item(body: MenuItemIn, user=Depends(require_role(Role.manager)), db: Session = Depends(get_db)):
    with db.begin():
        item = MenuItem(name=body.name, price=body.price, stock=body.stock, tags=body.tags)
        db.add(item)
        db.flush()                                 # so item.id exists for the audit row
        _audit(db, user.id, "MENU_CREATED", f"menuitem:{item.id}")
    return _menu_dict(item)


@app.put("/menu/{item_id}")
def update_menu_item(item_id: int, body: MenuItemUpdate,
                     user=Depends(require_role(Role.manager)), db: Session = Depends(get_db)):
    with db.begin():
        item = db.scalar(select(MenuItem).where(MenuItem.id == item_id).with_for_update())
        if not item:
            raise HTTPException(404, "Item not found")
        # Only overwrite the fields the manager actually sent
        if body.name is not None:
            item.name = body.name
        if body.price is not None:
            item.price = body.price                # old orders keep their own price snapshot (OrderLine.price)
        if body.tags is not None:
            item.tags = body.tags
        _audit(db, user.id, "MENU_UPDATED", f"menuitem:{item.id}")
    return _menu_dict(item)


@app.put("/menu/{item_id}/stock")
def set_menu_stock(item_id: int, body: StockIn,
                   user=Depends(require_role(Role.manager)), db: Session = Depends(get_db)):
    with db.begin():
        item = db.scalar(select(MenuItem).where(MenuItem.id == item_id).with_for_update())
        if not item:
            raise HTTPException(404, "Item not found")
        item.stock = body.stock                    # today's stock; the DB CHECK keeps it >= 0
        _audit(db, user.id, "STOCK_SET", f"menuitem:{item.id}")
    return _menu_dict(item)


# ======================================================================================
# FR-03: SLOTS (remaining capacity)
# ======================================================================================
SLOT_CAPACITY = 20                                 # max orders per slot (FR-03)

@app.get("/slots")
def list_slots(day: Optional[date] = None, user=Depends(current_user), db: Session = Depends(get_db)):
    day = day or datetime.now().date()
    start = datetime(day.year, day.month, day.day, 8, 0)     # first slot 08:00
    end = datetime(day.year, day.month, day.day, 15, 0)      # last slot starts 14:45, ends 15:00

    # One query: orders per slot_start, cancelled orders do not occupy a slot
    rows = db.execute(
        select(Order.slot_start, func.count(Order.id))
        .where(Order.slot_start >= start, Order.slot_start < end, Order.state != OrderState.cancelled)
        .group_by(Order.slot_start)).all()
    taken_by_slot = {r[0]: r[1] for r in rows}

    earliest = datetime.now() + timedelta(minutes=20)        # same 20-minute rule as place_order
    slots = []
    t = start
    while t < end:
        taken = taken_by_slot.get(t, 0)
        remaining = max(0, SLOT_CAPACITY - taken)
        slots.append({"slot_start": t.isoformat(), "taken": taken, "remaining": remaining,
                      "bookable": remaining > 0 and t >= earliest})
        t += timedelta(minutes=15)
    return slots


# ======================================================================================
# FR-05: CANCEL
# ======================================================================================
def _refund_order(db: Session, order: Order, now: datetime):
    """Refund the full total, restore stock, mark the order cancelled.
    Must run INSIDE a `with db.begin()` block. Also reusable for FR-12 (item withdrawal) later."""
    # Lock the wallet row, then write the refund ledger row (balance == sum of ledger)
    wallet = db.scalar(select(Wallet).where(Wallet.user_id == order.customer_id).with_for_update())
    db.add(WalletTransaction(wallet_id=wallet.id, amount=order.total,
                             kind=TxKind.refund, reference=f"order:{order.id}"))
    wallet.balance += order.total

    # Restore stock (FR-10), items locked in id order like place_order to avoid deadlocks
    lines = db.scalars(select(OrderLine).where(OrderLine.order_id == order.id)).all()
    for ln in sorted(lines, key=lambda x: x.item_id):
        item = db.scalar(select(MenuItem).where(MenuItem.id == ln.item_id).with_for_update())
        item.stock += ln.quantity

    order.state = OrderState.cancelled
    order.closed_at = now


@app.post("/orders/{order_id}/cancel")
def cancel_order(order_id: int, user=Depends(require_role(Role.customer)), db: Session = Depends(get_db)):
    now = datetime.now()
    with db.begin():
        order = db.scalar(select(Order).where(Order.id == order_id).with_for_update())
        if not order:
            raise HTTPException(404, "Order not found")
        if order.customer_id != user.id:                      # customers cancel only their own orders
            raise HTTPException(403, "Not your order")
        if order.state != OrderState.placed:                  # kitchen already started it, or it is closed
            raise HTTPException(409, "Order can no longer be cancelled")
        if now > order.slot_start - timedelta(minutes=15):    # cancellation window closed
            raise HTTPException(409, "Too late: cancellation closes 15 minutes before the slot")
        _refund_order(db, order, now)
        _audit(db, user.id, "ORDER_CANCELLED", f"order:{order.id}")
    return {"status": "cancelled", "order_id": order.id, "refunded": order.total}


# NEW: small helper endpoint so the customer UI can show their orders and the pickup code (FR-06).
# The code is only revealed when the order is ready.
@app.get("/orders/mine")
def my_orders(user=Depends(require_role(Role.customer)), db: Session = Depends(get_db)):
    orders = db.scalars(select(Order).where(Order.customer_id == user.id)
                        .order_by(Order.slot_start.desc())).all()
    return [{"order_id": o.id, "slot_start": o.slot_start.isoformat(), "state": o.state.value,
             "total": o.total,
             "pickup_code": o.pickup_code if o.state == OrderState.ready else None}
            for o in orders]


# ======================================================================================
# FR-06: KITCHEN
# ======================================================================================
@app.get("/kitchen/queue")
def kitchen_queue(user=Depends(require_role(Role.kitchen)), db: Session = Depends(get_db)):
    today = datetime.now().date()
    day_start = datetime(today.year, today.month, today.day)
    orders = db.scalars(
        select(Order).where(Order.slot_start >= day_start,
                            Order.slot_start < day_start + timedelta(days=1),
                            Order.state.in_([OrderState.placed, OrderState.preparing, OrderState.ready]))
        .order_by(Order.slot_start, Order.id)).all()
    queue = []
    for o in orders:
        items = db.execute(                                   # item names + quantities of this order
            select(MenuItem.name, OrderLine.quantity)
            .join(MenuItem, MenuItem.id == OrderLine.item_id)
            .where(OrderLine.order_id == o.id)).all()
        # pickup_code is NOT sent to the kitchen; the customer shows it at the counter
        queue.append({"order_id": o.id, "slot_start": o.slot_start.isoformat(), "state": o.state.value,
                      "items": [{"name": n, "quantity": q} for n, q in items]})
    return queue


def notify_customer_ready(customer_email: str, order_id: int):
    # STUB (FR-06): replace with e-mail / browser push later. For now just log it.
    print(f"[NOTIFY] {customer_email}: order {order_id} is ready, see your pickup code in the app")


def _kitchen_transition(db: Session, order_id: int, user: User,
                        from_state: OrderState, to_state: OrderState, action: str):
    """Valid transitions only: placed -> preparing -> ready."""
    with db.begin():
        order = db.scalar(select(Order).where(Order.id == order_id).with_for_update())
        if not order:
            raise HTTPException(404, "Order not found")
        if order.state != from_state:
            raise HTTPException(409, f"Order is {order.state.value}, expected {from_state.value}")
        order.state = to_state
        if to_state == OrderState.ready:
            order.ready_at = datetime.now()                   # the uncollected job counts from the slot, not from here
        _audit(db, user.id, action, f"order:{order.id}")
        customer_email = db.scalar(select(User.email).where(User.id == order.customer_id))
    if to_state == OrderState.ready:
        notify_customer_ready(customer_email, order_id)       # outside the transaction: a failed notice must not undo it
    return {"status": to_state.value, "order_id": order_id}


@app.post("/orders/{order_id}/preparing")
def mark_preparing(order_id: int, user=Depends(require_role(Role.kitchen)), db: Session = Depends(get_db)):
    return _kitchen_transition(db, order_id, user, OrderState.placed, OrderState.preparing, "ORDER_PREPARING")


@app.post("/orders/{order_id}/ready")
def mark_ready(order_id: int, user=Depends(require_role(Role.kitchen)), db: Session = Depends(get_db)):
    return _kitchen_transition(db, order_id, user, OrderState.preparing, OrderState.ready, "ORDER_READY")


# ======================================================================================
# FR-07: PICKUP AT THE COUNTER
# ======================================================================================
class PickupIn(BaseModel):
    code: str = Field(pattern=r"^\d{4}$")          # exactly 4 digits (FR-07)

@app.post("/orders/{order_id}/pickup")
def pickup_order(order_id: int, body: PickupIn,
                 user=Depends(require_role(Role.cashier)), db: Session = Depends(get_db)):
    with db.begin():
        order = db.scalar(select(Order).where(Order.id == order_id).with_for_update())
        if not order:
            raise HTTPException(404, "Order not found")
        if order.state != OrderState.ready:
            raise HTTPException(409, f"Order is {order.state.value}, not ready")
        # compare_digest = constant-time comparison (no timing leak of the code)
        if not secrets.compare_digest(order.pickup_code, body.code):
            raise HTTPException(403, "Wrong pickup code")
        order.state = OrderState.collected
        order.closed_at = datetime.now()
        _audit(db, user.id, "ORDER_COLLECTED", f"order:{order.id}")
    return {"status": "collected", "order_id": order.id}


# ======================================================================================
# FR-13: WALLET TOP-UP
# ======================================================================================
class TopupIn(BaseModel):
    customer_email: str
    amount: int = Field(gt=0)                      # fils, must be positive

@app.post("/wallet/topup", status_code=201)
def topup_wallet(body: TopupIn, user=Depends(require_role(Role.cashier)), db: Session = Depends(get_db)):
    with db.begin():                               # ledger row + balance change commit together
        target = db.scalar(select(User).where(User.email == body.customer_email))
        if not target:
            raise HTTPException(404, "Customer not found")
        wallet = db.scalar(select(Wallet).where(Wallet.user_id == target.id).with_for_update())
        if not wallet:
            raise HTTPException(404, "Customer has no wallet")
        db.add(WalletTransaction(wallet_id=wallet.id, amount=body.amount, kind=TxKind.topup,
                                 reference=f"cashier:{user.id}"))   # same reference format as the seed data
        wallet.balance += body.amount
        _audit(db, user.id, "WALLET_TOPUP", f"wallet:{wallet.id}")
    return {"status": "topped_up", "balance": wallet.balance}


# ======================================================================================
# FR-08 / FR-09: UNCOLLECTED ORDERS JOB
# ======================================================================================
def mark_uncollected_orders() -> int:
    """Ready orders whose slot ended more than 20 minutes ago become 'uncollected':
    no refund, one Strike. 3 strikes in the last 30 days block the customer for 7 days.
    Uses its own Session because it runs in a scheduler thread, not inside a request.
    Safe to run twice at once: rows are locked and the state is re-checked by the query."""
    now = datetime.now()
    # slot_start + 15 min (slot length) + 20 min (grace) < now   <=>   slot_start < now - 35 min
    cutoff = now - timedelta(minutes=35)
    count = 0
    with Session(engine) as db:
        with db.begin():
            overdue = db.scalars(
                select(Order).where(Order.state == OrderState.ready, Order.slot_start < cutoff)
                .with_for_update()).all()
            for order in overdue:
                order.state = OrderState.uncollected
                order.closed_at = now
                db.add(Strike(user_id=order.customer_id, order_id=order.id, time=now))
                # AuditEntry.actor_id is NOT NULL and there is no "system" user in the schema,
                # so the customer is used as actor. A dedicated system user would be cleaner.
                _audit(db, order.customer_id, "ORDER_UNCOLLECTED", f"order:{order.id}")

                db.flush()                                    # make the new Strike visible to the count below
                strikes = db.scalar(select(func.count(Strike.id)).where(
                    Strike.user_id == order.customer_id,
                    Strike.time >= now - timedelta(days=30)))
                if strikes >= 3:
                    customer = db.get(User, order.customer_id)
                    # do not extend a block that is already running
                    if not customer.blocked_until or customer.blocked_until <= now:
                        customer.blocked_until = now + timedelta(days=7)
                count += 1
    return count


# Scheduler: every minute, hours 07:00-15:59 (covers the 07:00-16:00 window).
# NOTE: with several uvicorn workers every worker would start this job; it is still correct
# (rows are locked) but wasteful. Use one worker for the pilot.
scheduler = BackgroundScheduler()

@app.on_event("startup")
def start_scheduler():
    scheduler.add_job(mark_uncollected_orders, "cron", minute="*", hour="7-15",
                      id="uncollected_job", replace_existing=True)
    scheduler.start()

@app.on_event("shutdown")
def stop_scheduler():
    scheduler.shutdown(wait=False)


# NEW: lets you trigger the job by hand to demo / test objective 3 ("simulated week")
# without waiting for the clock. Admin only.
@app.post("/admin/run-uncollected-job")
def run_uncollected_job(user=Depends(require_role(Role.admin))):
    return {"marked_uncollected": mark_uncollected_orders()}