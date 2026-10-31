"""
CafeQuick test database (SQLModel + SQLite).
Based on the baseline domain model in the project brief (section 29.5.3).

Run:  pip install sqlmodel
      python cafequick_db.py        -> creates cafequick_test.db and fills it with demo data
In your backend:  from cafequick_db import engine, User, Wallet, ...
"""
import random
from datetime import datetime, timedelta
from enum import Enum
from typing import List, Optional

from pydantic import NaiveDatetime  # naive (no timezone) datetimes, newer SQLModel requires this annotation
from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlmodel import Field, Relationship, Session, SQLModel, create_engine, select

# ---------------------------------------------------------------- enums
class Role(str, Enum):                      # FR-01 roles
    customer = "customer"
    kitchen = "kitchen"
    cashier = "cashier"
    manager = "manager"
    admin = "admin"

class OrderState(str, Enum):                # 6-state order life cycle (29.5.2)
    placed = "placed"
    preparing = "preparing"
    ready = "ready"
    collected = "collected"
    cancelled = "cancelled"
    uncollected = "uncollected"

class TxKind(str, Enum):                    # wallet ledger entry kinds
    topup = "topup"
    payment = "payment"
    refund = "refund"

# ---------------------------------------------------------------- tables
# Money is stored as integer fils (1 JD = 1000 fils) so balances are exact (constraint in 29.3.5).

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    email: str = Field(index=True, unique=True)      # university e-mail, SSO identity
    role: Role = Role.customer
    blocked_until: Optional[NaiveDatetime] = None         # set by the 3-strikes rule (FR-09)

    wallet: Optional["Wallet"] = Relationship(back_populates="user")
    orders: List["Order"] = Relationship(back_populates="customer")

class Wallet(SQLModel, table=True):
    # CHECK constraint: wallet can never go below zero (objective 2)
    __table_args__ = (CheckConstraint("balance >= 0", name="wallet_non_negative"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", unique=True)
    balance: int = 0                                  # fils; must equal sum of its transactions

    user: Optional[User] = Relationship(back_populates="wallet")
    transactions: List["WalletTransaction"] = Relationship(back_populates="wallet")

class WalletTransaction(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    wallet_id: int = Field(foreign_key="wallet.id", index=True)
    amount: int                                       # +fils for topup/refund, -fils for payment
    kind: TxKind
    reference: Optional[str] = None                   # e.g. "order:12"
    time: NaiveDatetime = Field(default_factory=datetime.now)

    wallet: Optional[Wallet] = Relationship(back_populates="transactions")

class MenuItem(SQLModel, table=True):
    # CHECK constraint: stock can never be negative (objective 2)
    __table_args__ = (CheckConstraint("stock >= 0", name="stock_non_negative"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    price: int                                        # fils
    stock: int = 0                                    # today's remaining stock
    tags: str = ""                                    # comma separated dietary/allergen tags (FR-14)
    available: bool = True                            # False = withdrawn by kitchen (FR-12)

class Order(SQLModel, table=True):
    # One order per customer per slot (FR-03)
    __table_args__ = (UniqueConstraint("customer_id", "slot_start", name="one_order_per_slot"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    customer_id: int = Field(foreign_key="user.id", index=True)
    slot_start: NaiveDatetime = Field(index=True)          # 15-min slot, max 20 orders (enforce in API)
    state: OrderState = OrderState.placed
    total: int = 0                                    # fils
    pickup_code: str = Field(default="0000", max_length=4)   # 4-digit code (FR-07)
    created_at: NaiveDatetime = Field(default_factory=datetime.now)
    ready_at: Optional[NaiveDatetime] = None
    closed_at: Optional[NaiveDatetime] = None              # collected / cancelled / uncollected time

    customer: Optional[User] = Relationship(back_populates="orders")
    lines: List["OrderLine"] = Relationship(back_populates="order")

class OrderLine(SQLModel, table=True):
    __table_args__ = (CheckConstraint("quantity BETWEEN 1 AND 5", name="qty_1_to_5"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    order_id: int = Field(foreign_key="order.id", index=True)
    item_id: int = Field(foreign_key="menuitem.id")
    quantity: int = 1
    price: int = 0                                    # unit price at order time (snapshot)

    order: Optional[Order] = Relationship(back_populates="lines")

class Strike(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    order_id: int = Field(foreign_key="order.id", unique=True)   # one strike per uncollected order
    time: NaiveDatetime = Field(default_factory=datetime.now)

class AuditEntry(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    actor_id: int = Field(foreign_key="user.id")
    action: str                                       # e.g. "ORDER_PLACED", "ORDER_READY"
    target: str                                       # e.g. "order:3"
    timestamp: NaiveDatetime = Field(default_factory=datetime.now)

# ---------------------------------------------------------------- engine
engine = create_engine("sqlite:///cafequick_test.db", echo=False)

def init_db() -> None:
    """Drop and recreate all tables (test DB only!)."""
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)

# ---------------------------------------------------------------- seed data
MENU = [  # (name, price in fils, stock, tags)
    ("Chicken Shawarma", 2500, 40, "halal"),
    ("Falafel Sandwich", 1000, 60, "vegan,halal"),
    ("Beef Burger", 3000, 30, "halal,gluten"),
    ("Margherita Pizza Slice", 1200, 50, "vegetarian,gluten,dairy"),
    ("Hummus Plate", 1500, 25, "vegan,halal"),
    ("Caesar Salad", 2200, 20, "dairy,egg"),
    ("Mansaf Portion", 3500, 15, "halal,dairy"),
    ("Cheese Manakish", 800, 45, "vegetarian,gluten,dairy"),
    ("Orange Juice", 700, 70, "vegan"),
    ("Coffee", 600, 80, "caffeine"),
]

def _pay(session: Session, wallet: Wallet, order: Order, when: datetime) -> None:
    """Write the payment ledger row and reduce the cached balance (FR-04)."""
    session.add(WalletTransaction(wallet_id=wallet.id, amount=-order.total,
                                  kind=TxKind.payment, reference=f"order:{order.id}", time=when))
    wallet.balance -= order.total

def _refund(session: Session, wallet: Wallet, order: Order, when: datetime) -> None:
    """Write the refund ledger row and restore the cached balance (FR-05)."""
    session.add(WalletTransaction(wallet_id=wallet.id, amount=order.total,
                                  kind=TxKind.refund, reference=f"order:{order.id}", time=when))
    wallet.balance += order.total

def seed(n_customers: int = 20) -> None:
    random.seed(42)                                   # deterministic data = repeatable tests
    init_db()
    now = datetime.now().replace(second=0, microsecond=0)
    with Session(engine) as s:
        # --- staff users (one per role) + customers
        staff = [User(name=f"{r.value.title()} User", email=f"{r.value}@uni.edu", role=r)
                 for r in (Role.kitchen, Role.cashier, Role.manager, Role.admin)]
        customers = [User(name=f"Student {i}", email=f"student{i}@uni.edu") for i in range(1, n_customers + 1)]
        s.add_all(staff + customers)
        s.commit()
        cashier = next(u for u in staff if u.role == Role.cashier)

        # --- wallets with an initial cashier top-up (FR-13); user #20 stays at zero for "insufficient funds" tests
        wallets = {}
        for c in customers:
            w = Wallet(user_id=c.id, balance=0)
            s.add(w); s.commit(); s.refresh(w)
            if c.id != customers[-1].id:
                amount = random.choice([50000, 75000, 100000])  # fils; large enough to cover seeded orders
                s.add(WalletTransaction(wallet_id=w.id, amount=amount, kind=TxKind.topup,
                                        reference=f"cashier:{cashier.id}", time=now - timedelta(days=1)))
                w.balance = amount
            wallets[c.id] = w
        for st in staff:                              # staff wallets (all roles have a wallet per FR-01)
            s.add(Wallet(user_id=st.id, balance=0))

        # --- menu
        items = [MenuItem(name=n, price=p, stock=st, tags=t) for n, p, st, t in MENU]
        items[6].available = False                    # withdrawn item for FR-12 tests (Mansaf)
        s.add_all(items); s.commit()

        # --- orders covering every state. slot offsets are in minutes relative to now.
        # (state, minutes until slot start, customer index)
        plan = [
            (OrderState.placed,      90, 0), (OrderState.placed,      90, 1),   # same slot, 2 orders
            (OrderState.placed,      45, 2),                                     # cancellable window edge
            (OrderState.preparing,   30, 3),
            (OrderState.ready,        0, 4),
            (OrderState.collected,  -60, 5), (OrderState.collected, -120, 6),
            (OrderState.cancelled,   60, 7),
            (OrderState.uncollected, -90, 8),
            # customer 10: three uncollected orders -> should be blocked (FR-09)
            (OrderState.uncollected, -300, 9), (OrderState.uncollected, -240, 9), (OrderState.uncollected, -180, 9),
        ]
        avail = [i for i in items if i.available]
        for state, off, ci in plan:
            cust = customers[ci]
            slot = (now + timedelta(minutes=off)).replace(minute=((now + timedelta(minutes=off)).minute // 15) * 15)
            # uncollected orders on the same day for the same customer need distinct slots (unique constraint)
            order = Order(customer_id=cust.id, slot_start=slot, state=state,
                          pickup_code=f"{random.randint(0, 9999):04d}", created_at=slot - timedelta(hours=2))
            s.add(order); s.commit(); s.refresh(order)

            # 1-3 lines per order, stock reserved at placement (FR-10)
            for it in random.sample(avail, random.randint(1, 3)):
                q = random.randint(1, 2)
                s.add(OrderLine(order_id=order.id, item_id=it.id, quantity=q, price=it.price))
                order.total += it.price * q
                it.stock -= q
            _pay(s, wallets[cust.id], order, order.created_at)

            if state in (OrderState.ready, OrderState.collected, OrderState.uncollected):
                order.ready_at = slot - timedelta(minutes=5)
            if state in (OrderState.collected, OrderState.uncollected, OrderState.cancelled):
                order.closed_at = slot + timedelta(minutes=5)
            if state == OrderState.cancelled:         # full refund + stock restored (FR-05)
                _refund(s, wallets[cust.id], order, order.closed_at)
                for ln in s.exec(select(OrderLine).where(OrderLine.order_id == order.id)).all():
                    next(i for i in items if i.id == ln.item_id).stock += ln.quantity
            if state == OrderState.uncollected:       # no refund, one strike (FR-08)
                s.add(Strike(user_id=cust.id, order_id=order.id, time=slot + timedelta(minutes=35)))
            s.add(AuditEntry(actor_id=cust.id, action="ORDER_PLACED", target=f"order:{order.id}",
                             timestamp=order.created_at))
            s.commit()

        # --- apply the 3-strike block for customer index 9
        customers[9].blocked_until = now + timedelta(days=7)
        s.add(customers[9]); s.commit()

        # --- sanity check: cached balance must equal ledger sum
        for w in s.exec(select(Wallet)).all():
            total = sum(t.amount for t in w.transactions)
            assert total == w.balance, f"wallet {w.id} ledger mismatch"
    print("Seeded OK -> cafequick_test.db")

if __name__ == "__main__":
    seed()
