"""
CafeQuick account management (FR-01, FR-04, NFR-03, NFR-05).
Adds three endpoints without touching the rest of main.py:
    POST /signup          create a customer account and choose the opening wallet balance
    GET  /me              who am I: name, role, wallet balance (used by the pages after sign-in)
    GET  /wallet/history  wallet balance + last 30 ledger rows
Hook-up (two lines at the END of Backend/main.py):
    from Backend.accounts import make_accounts_router
    app.include_router(make_accounts_router(get_db, current_user))
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cafequick_db import AuditEntry, Role, TxKind, User, Wallet, WalletTransaction

# ---- demo switches -------------------------------------------------------------------
# The brief (FR-13) says only a cashier puts money in a wallet. Letting a customer choose
# their own opening balance is a DEMO feature: anyone can create money. Set this to False
# before a real pilot and sign-up will only accept an opening balance of 0.
ALLOW_SELF_FUNDING = True
MAX_SIGNUP_BALANCE = 100_000                      # fils = 100 JD, the most a new account may start with


class SignupIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: str = Field(max_length=120)
    initial_balance: int = Field(default=0, ge=0)  # fils, same unit as everywhere else


def make_accounts_router(get_db, current_user) -> APIRouter:
    """A factory, so this file can use main.py's get_db / current_user without importing main
    (importing main from here would be a circular import)."""
    router = APIRouter()

    @router.post("/signup", status_code=201)
    def signup(body: SignupIn, db: Session = Depends(get_db)):
        email = body.email.strip().lower()            # same case as the seed users
        if not email:                                 # any text is accepted as the e-mail, even a fake one (demo)
            raise HTTPException(422, "Enter an e-mail")
        if body.initial_balance > MAX_SIGNUP_BALANCE:
            raise HTTPException(422, f"The opening balance can be at most {MAX_SIGNUP_BALANCE} fils")
        if body.initial_balance and not ALLOW_SELF_FUNDING:
            raise HTTPException(403, "Wallets are loaded by a cashier")

        try:
            with db.begin():                          # user + wallet + ledger row + audit commit together
                if db.scalar(select(User).where(User.email == email)):
                    raise HTTPException(409, "This e-mail already has an account")
                # Role is NOT read from the request: this endpoint can only create customers (NFR-03)
                user = User(name=body.name.strip(), email=email, role=Role.customer)
                db.add(user)
                db.flush()                            # so user.id exists
                wallet = Wallet(user_id=user.id, balance=body.initial_balance)
                db.add(wallet)
                db.flush()
                if body.initial_balance:              # keep "balance == sum of ledger" true from day one
                    db.add(WalletTransaction(wallet_id=wallet.id, amount=body.initial_balance,
                                             kind=TxKind.topup, reference="signup"))
                db.add(AuditEntry(actor_id=user.id, action="ACCOUNT_CREATED", target=f"user:{user.id}"))
        except IntegrityError:                        # two sign-ups with the same e-mail at the same moment
            raise HTTPException(409, "This e-mail already has an account")
        return {"status": "created", "user_id": user.id, "email": email, "balance": body.initial_balance}

    @router.get("/me")
    def me(user=Depends(current_user), db: Session = Depends(get_db)):
        wallet = db.scalar(select(Wallet).where(Wallet.user_id == user.id))
        return {"id": user.id, "name": user.name, "email": user.email, "role": user.role.value,
                "balance": wallet.balance if wallet else 0,
                "blocked_until": user.blocked_until.isoformat() if user.blocked_until else None}

    @router.get("/wallet/history")
    def wallet_history(user=Depends(current_user), db: Session = Depends(get_db)):
        wallet = db.scalar(select(Wallet).where(Wallet.user_id == user.id))
        if not wallet:
            return {"balance": 0, "transactions": []}
        rows = db.scalars(select(WalletTransaction).where(WalletTransaction.wallet_id == wallet.id)
                          .order_by(WalletTransaction.id.desc()).limit(30)).all()
        return {"balance": wallet.balance,
                "transactions": [{"amount": t.amount, "kind": t.kind.value, "reference": t.reference,
                                  "time": t.time.isoformat()} for t in rows]}

    return router
