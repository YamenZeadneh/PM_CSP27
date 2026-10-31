import secrets
import sys
from datetime import datetime, timedelta
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, Header
from pydantic import BaseModel, Field
from sqlalchemy import select, func      # FIX: one import, "select" was imported twice
from sqlalchemy.orm import Session

# FIX: add the ../Database folder to Python's import path so "cafequick_db" can be found
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "Database"))

# FIX: import the module by name (cafequick_db), not by file path; engine and User added for get_db/current_user
from cafequick_db import (engine, User, MenuItem, Wallet, WalletTransaction, Order, OrderLine,
                          OrderState, TxKind, AuditEntry)
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


@app.post("/orders", status_code=201)
def place_order(body: OrderIn, user=Depends(current_user), db: Session = Depends(get_db)):
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