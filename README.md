# PM_CSP27
CafeQuick: Cafeteria Pre-Order & Pickup System (SE440 capstone, JUST)

Contents: 1 Run locally | 2 Project in 5 lines | 3 Architecture and file map | 4 Business rules and where they live | 5 Walkthrough of place_order | 6 Concepts you must be able to explain | 7 Order life cycle | 8 Accounts and roles | 9 REST API | 10 Tests | 11 Front end | 12 Gaps vs the brief (be honest in the exam) | 13 Likely exam questions | 14 Presentation outline | 15 Sources to study | 16 Diagrams (PMP 5 and 6)

---

## 1. تشغيل المشروع

> الكودات هون نقطة بداية مش اشي رسمي. عدلو عليها زي ما بدكم.

### 1.1 تنزيل الباكجات المطلوبة

بايثون 3.10 او اعلى. شغلو الامر من المجلد الرئيسي للمشروع:

```
pip install fastapi uvicorn pydantic sqlalchemy sqlmodel apscheduler pytest pytest-cov httpx
```

- `sqlmodel` ضروري لملف الداتا بيس، و `pytest` و `pytest-cov` و `httpx` للتستات.

### 1.2 الداتا بيس (اول مرة او لما بدكم ترجعو البيانات الاصلية)

```
python Database/cafequick_db.py
```

- بينشئ ملف `cafequick_test.db` وبيعبيه بيانات تجريبية (20 زبون، 4 موظفين، 10 اصناف، طلبات بكل الحالات).
- انتبهو: بيمسح كل البيانات القديمة قبل ما يعبي من جديد.
- ملف `cafequick_test.db` مش لازم ينرفع على GitHub. ضيفوه على `.gitignore`.

### 1.3 تشغيل الباك ايند

```
uvicorn Backend.main:app --reload
```

- شغلوه من المجلد الرئيسي (مش من جوا مجلد Backend).
- التوثيق التلقائي للـ API بيطلع على: http://127.0.0.1:8000/docs
- لازم يكون بآخر `Backend/main.py` هالسطرين (هني اللي بيفعلو التسجيل وصفحة المحفظة):

```python
from Backend.accounts import make_accounts_router
app.include_router(make_accounts_router(get_db, current_user))
```

### 1.4 تشغيل الفرونت ايند

افتحو تيرمينل جديد:

```
cd Frontend
python3 -m http.server 5500
```

- صفحة الزبون: http://localhost:5500
- صفحة الموظفين (شيف، كاشير، مدير، ادمن): http://localhost:5500/staff.html
- استخدمو `localhost` او `127.0.0.1` مش `0.0.0.0`. الباك ايند بيسمح (CORS) بس لهدول العنوانين، و `0.0.0.0` اصلا ما بيفتح بالمتصفح.
- على ويندوز لو طلع `Python was not found` شغلو الامر من WSL او استخدمو `python` بدل `python3`.
- لو غيرتو ملفات الفرونت وما ظهر التغيير، اعملو Ctrl+F5.

### 1.5 تشغيل التستات

```
pytest Tests --cov=Backend --cov-report=term-missing
```

- شغلوها من المجلد الرئيسي. كل تست بيستخدم داتا بيس مؤقتة، فما بتمس `cafequick_test.db`.
- المطلوب بالـ brief (NFR-08): تغطية 70% على الاقل.

### 1.6 هيكلية المشروع

```
PM_CSP27/
  Backend/
    main.py            الـ API الرئيسي: الطلبات، المطبخ، المحفظة، التقارير، job الطلبات غير المستلمة
    accounts.py        التسجيل (signup) و /me و سجل المحفظة
  Database/
    cafequick_db.py    الجداول + البيانات التجريبية
  Frontend/
    index.html         صفحة الزبون (تسجيل دخول، انشاء حساب، طلب، طلباتي، المحفظة)
    staff.html         صفحة الموظفين (مطبخ، كاشير، تقرير، ادمن)
    common.js          الكود المشترك: الطلبات للـ API، تسجيل الدخول، التابات
    customer.js        شاشات الزبون
    staff.js           شاشات الموظفين
    style.css
  Tests/
    conftest.py        اعدادات التستات (داتا بيس مؤقتة + ساعة ثابتة)
    test_backend.py
    test_accounts.py
```

- تنظيف: اذا لسا موجودين، احذفو `Frontend/app.js` و `Frontend/accounts.py` و `Frontend/test_accounts.py`. هدول نسخ قديمة او مكررة من ملفات موجودة بمكانها الصحيح.

Quick demo path: seed DB, start backend, start front end, sign in as `student1@uni.edu` (page 1), place an order; sign in as `kitchen@uni.edu` (staff page) and mark preparing then ready; as the customer read the pickup code in "My orders"; as `cashier@uni.edu` hand it over with order number and code.

---

## 2. Project in 5 lines

- Web app: customers pre-order food for a 15-minute pickup slot and pay from a campus wallet.
- Kitchen sees a queue by slot; cashier hands over against a 4-digit code and tops up wallets; manager sees a daily report; admin sees the audit log.
- Rules that cost money or fairness (slot capacity, stock, wallet, refunds, strikes) are enforced in the back end inside one database transaction, never only in the browser.
- Stack: FastAPI (Python) + SQLModel/SQLAlchemy + SQLite (dev/tests) or PostgreSQL (pilot) + plain HTML/CSS/JavaScript + APScheduler + pytest.
- Sign-in is simulated SSO (e-mail in the `X-User-Email` header). No passwords exist.

---

## 3. Architecture and file map

Three tiers: browser front end -> REST API (modular monolith, one deployable) -> relational DB. One extra component: a scheduled job inside the API process.

| File | Responsibility |
|---|---|
| `Database/cafequick_db.py` | Tables (SQLModel), CHECK constraints, partial unique index, engine (`DATABASE_URL` env var, default SQLite), seed data |
| `Backend/main.py` | App, CORS, `get_db`, `current_user`, `require_role`, `_audit`, all endpoints, `_refund_order`, `mark_uncollected_orders`, scheduler |
| `Backend/accounts.py` | `/signup`, `/me`, `/wallet/history` via `make_accounts_router` (a factory, avoids circular import with main.py) |
| `Frontend/common.js` | `api()` request helper, sign-in, tabs per role, one delegated click listener, 15 s auto-refresh |
| `Frontend/customer.js` | Slots, menu, cart, my orders, wallet, sign-up |
| `Frontend/staff.js` | Kitchen queue, withdraw, cashier, report, stock editor, audit, job button |
| `Tests/conftest.py` | Temp DB per test, frozen clock (`CLOCK`, `FakeDatetime`), helpers (`make_user`, `make_item`, `add_order`, `balance_and_ledger`) |
| `Tests/test_backend.py`, `Tests/test_accounts.py` | Requirement-named tests |

Data model (money is integer fils, 1 JD = 1000 fils):
User 1-0..1 Wallet; Wallet 1-* WalletTransaction (ledger); User 1-* Order; Order 1-* OrderLine (price snapshot); Order 0..1 Strike; MenuItem 1-* OrderLine; AuditEntry (actor nullable = system).

---

## 4. Business rules and where they live

| Rule | Brief | Enforced in | Proven by |
|---|---|---|---|
| 1 to 5 lines, qty 1 to 5 | FR-03 | `OrderIn`/`LineIn` (Pydantic) + DB CHECK `qty_1_to_5` | `test_more_than_5_lines_rejected`, `test_quantity_above_5_is_422` |
| Slot on 15-min grid, 08:00 to 14:45 start | FR-03 | `place_order` | `test_invalid_slot_is_422` |
| At least 20 min ahead | FR-03 | `place_order` | `test_slot_less_than_20_minutes_ahead_is_422` |
| Max 20 orders per slot | FR-03 | `place_order` count + PG advisory lock | `test_slot_capacity_is_20_objective2` |
| One order per customer per slot | FR-03 | `place_order` check + partial unique index `one_order_per_slot` | `test_one_order_per_customer_per_slot`, `test_reorder_same_slot_after_cancel` |
| Pay from wallet, never below 0 | FR-04 | `place_order` + CHECK `wallet_non_negative` | `test_wallet_never_below_zero_...` |
| Stock reserved at order, released at cancel | FR-10 | `place_order`, `_refund_order` + CHECK `stock_non_negative` | `test_stock_is_never_oversold_objective2`, cancel tests |
| Cancel until 15 min before slot, only if `placed` | FR-05 | `cancel_order` | `test_cancel_before_window_...`, `test_cancel_after_window_is_409` |
| Kitchen placed -> preparing -> ready, customer notified | FR-06 | `_kitchen_transition` (notify is a log stub) | `test_kitchen_flow_and_pickup_code` |
| Pickup needs correct 4-digit code, cashier only | FR-07 | `pickup_order` (`compare_digest`) | same test |
| Ready order, slot_start + 35 min passed -> uncollected, no refund, strike | FR-08 | `mark_uncollected_orders` | `test_uncollected_orders_get_strike_...` |
| 3 strikes in 30 days -> blocked 7 days | FR-09 | `mark_uncollected_orders`, checked in `place_order` | same, `test_two_strikes_do_not_block`, `test_old_strikes_...` |
| Daily report | FR-11 | `daily_report` | `test_daily_report_numbers` |
| Withdraw item, refund `placed` orders only | FR-12 | `withdraw_menu_item` | `test_withdrawal_refunds_only_...` |
| Cashier top-up | FR-13 | `topup_wallet` | `test_topup_...` |
| Tags shown | FR-14 | `_menu_dict`, customer.js | `test_customer_sees_only_...` |
| Audit log | FR-16 | `_audit` inside each transaction, `/audit` | `test_audit_log_...` |
| Roles | FR-01 | `require_role` (401 then 403) | `test_role_is_enforced_403` |

The 35 minutes = 15-minute slot length + 20-minute grace. Know this number.

---

## 5. Walkthrough of place_order (the core of the project)

1. `require_role(customer)`: 401 if header missing/unknown, 403 if not a customer.
2. Cheap checks outside the transaction: 20 minutes ahead, grid and hours, not blocked.
3. `with db.begin()`: everything below commits together or rolls back together. Raising `HTTPException` rolls back.
4. PostgreSQL only: `pg_advisory_xact_lock(slot timestamp)` serializes orders for the same slot, so two requests cannot both read "19 orders".
5. Count non-cancelled orders in slot (>= 20 -> 409). Count customer's orders in slot (-> 409).
6. For each line, in `item_id` order: `SELECT ... FOR UPDATE` the item, check available and stock, decrement, add price x qty to total. Sorted order prevents deadlocks.
7. Lock wallet row, check balance (-> 402), subtract, add ledger row (kind payment, negative).
8. Insert Order (random 4-digit code with `secrets`), flush to get the id, insert OrderLines with price snapshot, set ledger reference `order:<id>`, add audit row.
9. Commit. Return id and total.

Why `current_user` calls `db.commit()`: its SELECT auto-starts a transaction on the shared session, and `with db.begin()` fails if one is open.

---

## 6. Concepts you must be able to explain

- **Transaction (ACID)**: money, stock and slot checks are one unit. Partial failure leaves nothing changed (test: wallet 500, cheap item + expensive item -> 402, stock of cheap item unchanged).
- **Row locks `FOR UPDATE`** and **lock ordering**: prevent lost updates and deadlocks. SQLite ignores them (one writer at a time), so the concurrency test is a smoke test only.
- **Advisory lock**: needed because "count orders in slot" has no row to lock.
- **Defense in depth**: Pydantic validation -> API checks -> DB CHECK constraints. Even buggy code cannot make a negative wallet or negative stock.
- **Ledger**: balance is a cached sum of `WalletTransaction` rows; `balance_and_ledger()` in tests asserts they match. `ledger_sign` CHECK stops wrong-sign rows.
- **Integer fils**: no floating point error with money.
- **Price snapshot** in `OrderLine.price`: later price edits do not change old orders.
- **Partial unique index** (`WHERE state != 'cancelled'`): one active order per customer per slot, but re-ordering after cancel works (this was a bug that returned 500).
- **Pickup code hidden until ready** and **never sent to kitchen**: kitchen cannot hand over by itself; only cashier verifies.
- **`secrets.compare_digest`**: constant-time compare.
- **Audit with `actor_id = None`** for system actions (scheduled job).
- **Scheduler**: APScheduler cron every minute, hours 7 to 15. One uvicorn worker only, otherwise each worker runs the job (still correct because of locks, but wasteful).
- **Idempotent job**: second run finds nothing (state already changed).
- **Frozen clock in tests**: business rules depend on time; `FakeDatetime` is patched into `main`. Note `accounts.py` uses the real clock (see `test_me_returns_strikes_30d`).
- **Event delegation** (front end): one `document` click listener handles every `data-action` button, including buttons created later by `innerHTML`.
- **`esc()`**: escapes text before `innerHTML` (XSS, OWASP A03).

---

## 7. Order life cycle

| From | To | Trigger | Function |
|---|---|---|---|
| (new) | placed | customer POST /orders | `place_order` |
| placed | cancelled | customer cancel (>= 15 min before slot) or kitchen withdraws an item | `cancel_order`, `withdraw_menu_item` |
| placed | preparing | kitchen | `_kitchen_transition` |
| preparing | ready | kitchen, sets `ready_at`, notifies | `_kitchen_transition` |
| ready | collected | cashier with correct code | `pickup_order` |
| ready | uncollected | job, slot_start < now - 35 min; strike, no refund | `mark_uncollected_orders` |
| placed or preparing | cancelled | job, same cutoff, kitchen never finished; full refund, NO strike, audit `ORDER_EXPIRED_REFUND` | `mark_uncollected_orders` (extra rule, not in the brief) |

---

## 8. Accounts and roles

Sign-in is a simulated single sign-on (NFR-03): the page sends the e-mail in the `X-User-Email` header and the backend looks it up. No password exists anywhere. The real system would use the university OpenID Connect provider (Keycloak is the planned test provider).

Each page accepts only its own kind of account. A staff account on `index.html`, or a customer account on `staff.html`, is refused with a message.

| E-mail | Role | Page | Notes |
|---|---|---|---|
| `student1@uni.edu` to `student20@uni.edu` | customer | `index.html` | Wallets start with 50, 75 or 100 JD. |
| `student20@uni.edu` | customer | `index.html` | Wallet is 0 JD, used for "insufficient balance" tests. |
| `student10@uni.edu` | customer | `index.html` | Blocked for 7 days (three strikes), used for FR-09 tests. |
| `kitchen@uni.edu` | kitchen | `staff.html` | Queue by slot, preparing, ready, withdraw an item. |
| `cashier@uni.edu` | cashier | `staff.html` | Hand over by pickup code, wallet top-up. |
| `manager@uni.edu` | manager | `staff.html` | Daily report, menu stock. |
| `admin@uni.edu` | admin | `staff.html` | Audit log, run the uncollected-orders job by hand. |

Staff accounts exist only in the seed data. Sign-up creates customers only (role is not read from the request body).

Warning: letting a customer pick their own opening balance (max 100 JD) is a demo feature and contradicts FR-13 (only a cashier loads wallets). Controlled by `ALLOW_SELF_FUNDING` in `Backend/accounts.py`; `False` = only 0 JD accepted.

---

## 9. REST API

All endpoints except `/signup` need the `X-User-Email` header. Interactive docs: `http://127.0.0.1:8000/docs`. Errors: 401 unknown user, 403 wrong role or rule (blocked, wrong code), 404 missing, 409 state/capacity/stock conflict, 402 insufficient balance, 422 validation.

| Method and path | Role | Requirement | What it does |
|---|---|---|---|
| `POST /signup` | public | FR-01, FR-04 | Create a customer account with an opening balance. |
| `GET /me` | any | FR-01 | Name, role, wallet balance, block status, strikes in 30 days. |
| `GET /wallet/history` | any | FR-04 | Balance and the last 30 ledger rows. |
| `GET /menu` | any | FR-02, FR-14 | Customers see available items in stock. Kitchen, manager and admin see all. |
| `POST /menu` | manager | FR-02 | Create an item. |
| `PUT /menu/{id}` | manager | FR-02 | Edit name, price, tags; can re-enable but not hide an item. |
| `PUT /menu/{id}/stock` | manager | FR-02 | Set today's stock. |
| `POST /menu/{id}/withdraw` | kitchen | FR-12 | Withdraw an item, refund orders not yet being prepared. |
| `GET /slots` | any | FR-03 | The 28 pickup slots with taken and remaining places. |
| `POST /orders` | customer | FR-03, FR-04, FR-10 | Place an order: slot, stock and wallet checks in one transaction. |
| `GET /orders/mine` | customer | FR-05, FR-06 | Own orders; the pickup code appears only when the order is ready. |
| `POST /orders/{id}/cancel` | customer | FR-05 | Cancel until 15 minutes before the slot; refund and restore stock. |
| `GET /kitchen/queue` | kitchen | FR-06 | Open orders of today by slot. |
| `POST /orders/{id}/preparing` | kitchen | FR-06 | placed to preparing. |
| `POST /orders/{id}/ready` | kitchen | FR-06 | preparing to ready, customer notified (currently a log stub). |
| `POST /orders/{id}/pickup` | cashier | FR-07 | Hand over against the 4-digit code. |
| `POST /wallet/topup` | cashier | FR-13 | Add money to a customer wallet. |
| `GET /reports/daily` | manager | FR-11 | Orders, collected, uncollected, cancelled, revenue, top 3 items. |
| `GET /audit` | admin | FR-16 | Audit log, newest first, optional `action` filter. |
| `POST /admin/run-uncollected-job` | admin | FR-08, FR-09 | Run the uncollected-orders job now. |

Report definitions: an order belongs to the day of its `slot_start`; revenue = collected + uncollected totals (cancelled were refunded, others not final); top items = by quantity in non-cancelled orders, name as tie-breaker.

---

## 10. Tests

Run: `pytest Tests --cov=Backend --cov-report=term-missing`. Each test gets a fresh SQLite file; the clock starts Monday 2026-11-09 07:00 and tests move `CLOCK["now"]`.

Groups: auth/roles, menu, ordering rules, cancellation, kitchen + pickup, top-up, uncollected job, withdrawal, manager CRUD, report, audit, concurrency smoke test, DB-constraint tests, accounts. Each test name carries the requirement or objective it proves (use this for the traceability matrix).

Objective 2 ("never overfill, oversell, or go below zero") is proven by: slot capacity test, stock test, wallet test, concurrency test, plus the DB CHECK constraints.
Objective 3 ("simulated week") is proven by the job tests and the admin "run job" endpoint.

---

## 11. Front end

- Two static pages, no framework. `data-page` on `<body>` tells `common.js` which account type the page accepts.
- `api(method, path, body, opts)` is the only function that calls `fetch`; it adds `X-User-Email`, shows toasts, and writes the last response into the "developer" box.
- `GET /me` after sign-in gives role and balance; tabs are built from the role (`TABS`). Backend still enforces roles (the UI is convenience, not security).
- Cart is built in the DOM (`#lines`); total is computed from `menuCache`; Place order is disabled when the cart is empty, the wallet is too low, or the user is blocked.
- Accessibility (NFR-06): skip link, focus outline, 44 px buttons, state shown as text not only colour, `aria-live` toast, `prefers-reduced-motion`.
- Email stored in `sessionStorage` to survive reload.

---

## 12. Gaps vs the brief (state these yourself before the examiner finds them)

- Sign-in header is forgeable: fails NFR-03 outside development. Real OpenID Connect not implemented.
- Ready notice is a `print`, no e-mail or push (FR-06 partial).
- Not done: loyalty points FR-15 (Could), hourly backups NFR-09, load test NFR-01, OWASP Top 10 check NFR-04, one-command deploy NFR-10, 5-year transaction retention policy NFR-05, availability measurement NFR-02.
- SQLite ignores row locks: concurrency not proven until tested on PostgreSQL.
- Self-funding sign-up contradicts FR-13.
- Extra behaviour not in brief: stuck-order auto-refund rule, strike counter in `/me`, `/signup`.
- Cancel rule in brief is "until 15 minutes before the slot while the kitchen has not started it"; code requires state `placed` and `now <= slot_start - 15 min`.
- Slot capacity 20 is hard-coded in both `main.py` (`SLOT_CAPACITY`) and `customer.js`.
- One uvicorn worker required (job duplication).
- Gantt dates are placeholders (week 1 = 2026-10-05).
- Code is partly AI-generated: the brief requires every use of generative AI to be declared in an appendix (tool, purpose, what was changed). Do this.

---

## 13. Likely exam questions (short answers)

1. How do you guarantee a slot never exceeds 20 orders? One transaction, count inside it, PostgreSQL advisory lock per slot, test with 21 users.
2. How is a negative wallet prevented? Balance check under row lock + CHECK `balance >= 0`.
3. Why a ledger? Auditability; finance can reconcile; balance == sum of rows.
4. Why integers for money? Exactness (constraint in 29.3.5).
5. A customer cancels 14 minutes before the slot. Result? 409, window closed.
6. Kitchen withdraws an item that is in a `preparing` order. Result? Order untouched; only `placed` orders are refunded.
7. When does a ready order become uncollected? When `slot_start + 15 + 20` minutes have passed (job runs every minute).
8. What happens at the third strike within 30 days? `blocked_until = now + 7 days`; `place_order` returns 403. A running block is not extended.
9. Why does the kitchen not see the pickup code? Prevents handing over without the customer; cashier verifies.
10. Why is the clock frozen in tests? Rules depend on time.
11. What would you change for production? Real OIDC, PostgreSQL, real notifications, backups, HTTPS reverse proxy, remove self-funding.
12. Why a modular monolith? Small team, one deployable, easy to test (ADR in PMP 5).
13. Change request scenario (Section C): trace FR -> design element -> code -> test using sections 4 and 10, then show the change-control steps from PMP 4/14.
14. Calculations (Section B: business case, earned value, risk reserve) use your own PMP figures; they are not in this repo. Re-derive them from your PMP 0, 7, 10 before the test.

---

## 14. Presentation outline (every member must speak; 6 marks)

1. Problem and goal, objectives (sponsor view).
2. Process: life cycle, schedule, cost, risk (PMP 2, 6, 7, 10).
3. Architecture: diagrams 1 to 3, ADRs.
4. Data model and the order state machine (diagrams 4, 5).
5. Core rules demo logic: place_order walkthrough (section 5).
6. Live demo: sign up, order, kitchen, ready, pickup, report, uncollected job via admin button, 3-strike block (`student10`).
7. Test evidence and coverage; security and gaps (section 12).
8. Lessons learned and closure.

---

## 15. Sources to study

Official:
- FastAPI tutorial (dependencies, security, testing): https://fastapi.tiangolo.com/tutorial/
- SQLModel: https://sqlmodel.tiangolo.com/
- SQLAlchemy 2.0 (sessions, transactions, `with_for_update`): https://docs.sqlalchemy.org/en/20/
- PostgreSQL explicit locking and advisory locks: https://www.postgresql.org/docs/current/explicit-locking.html
- SQLite partial indexes: https://www.sqlite.org/partialindex.html
- APScheduler user guide: https://apscheduler.readthedocs.io/
- pytest fixtures and monkeypatch: https://docs.pytest.org/
- OWASP Top 10: https://owasp.org/www-project-top-ten/
- OpenID Connect Core: https://openid.net/specs/openid-connect-core-1_0.html
- WCAG 2.1 quick reference: https://www.w3.org/WAI/WCAG21/quickref/
- C4 model: https://c4model.com/
- Mermaid syntax: https://mermaid.js.org/

Book (the official treatment of transactions, isolation, locks): Kleppmann, Designing Data-Intensive Applications, chapter 7.
Course side: PMBOK Guide (PMI) and SWEBOK V4 (IEEE Computer Society) for the PMP sections.

---

# 16. CafeQuick diagrams (PMP section 5 and 6)

Mermaid source. GitHub renders these blocks directly. To get images for the PDF, paste a block into
https://mermaid.live and export PNG/SVG (check it is readable when printed, as the brief requires).
Status: written from the brief and the current code; not yet reviewed by the team.
Diagrams 12 and 13 were added with the account pages; diagram 2 was updated for the two front-end pages.

## 1. C4 level 1: system context

```mermaid
flowchart LR
    cust["Customer<br/>student or staff"]
    kit["Kitchen staff"]
    cash["Cashier"]
    mgr["Manager and Admin"]
    cq["CafeQuick<br/>pre-order and pickup system"]
    idp["Identity provider<br/>OpenID Connect test provider"]
    mail["E-mail service"]
    push["Browser push service"]
    cust -->|"orders, cancels, sees pickup code"| cq
    kit -->|"sees queue, marks preparing and ready"| cq
    cash -->|"hands over by code, tops up wallets"| cq
    mgr -->|"menu, stock, reports, audit log"| cq
    cq -->|"authenticates users"| idp
    cq -->|"ready notices"| mail
    cq -->|"ready notices"| push
```

## 2. C4 level 2: containers

```mermaid
flowchart LR
    user["Browser<br/>customers and staff"]
    subgraph cafequick["CafeQuick"]
        fe["Front end<br/>HTML and JavaScript, two pages<br/>index.html customers, staff.html staff<br/>static files over HTTPS"]
        api["Back-end API<br/>Python FastAPI modular monolith<br/>main.py rules + accounts.py sign-up and /me<br/>owns slot, stock, wallet, cancel, pickup rules"]
        job["Uncollected-order job<br/>APScheduler inside the API process<br/>runs every minute 07:00-15:59"]
        db[("Relational database<br/>PostgreSQL for the pilot<br/>SQLite for dev and tests")]
    end
    idp["Identity provider<br/>Keycloak"]
    mail["E-mail service"]
    push["Browser push service"]
    user -->|HTTPS| fe
    fe -->|"REST JSON over HTTPS"| api
    api --> db
    job --> db
    api -->|OpenID Connect| idp
    api --> mail
    api --> push
```

## 3. Deployment view

```mermaid
flowchart TB
    subgraph client["Client devices"]
        b["Browsers: Chrome, Firefox, Safari, Edge<br/>phones from 360 px wide"]
    end
    subgraph host["Cloud free tier or university virtual machine"]
        proxy["Reverse proxy with TLS<br/>HTTPS only"]
        subgraph app["Application host"]
            static["Static front-end files"]
            uv["uvicorn, ONE worker<br/>FastAPI app + APScheduler job"]
        end
        pg[("PostgreSQL")]
        bk["Hourly backup job<br/>pg_dump 07:00-16:00<br/>restore tested before go-live"]
        kc["Keycloak test identity provider"]
    end
    ext["E-mail service and push service"]
    b -->|HTTPS 443| proxy
    proxy --> static
    proxy --> uv
    uv --> pg
    uv --> kc
    uv --> ext
    bk --> pg
    ci["Git repository and CI pipeline<br/>one pipeline run deploys (NFR-10)"] -.->|deploy| host
```

## 4. Entity-relationship diagram (matches Database/cafequick_db.py)

```mermaid
erDiagram
    USER ||--o| WALLET : has
    USER ||--o{ ORDER : places
    USER ||--o{ STRIKE : receives
    USER ||--o{ AUDITENTRY : performs
    WALLET ||--o{ WALLETTRANSACTION : "ledger rows"
    ORDER ||--|{ ORDERLINE : contains
    ORDER ||--o| STRIKE : "may cause"
    MENUITEM ||--o{ ORDERLINE : "appears in"
    USER {
        int id PK
        string name
        string email UK
        string role
        datetime blocked_until
    }
    WALLET {
        int id PK
        int user_id FK
        int balance "fils, CHECK >= 0"
    }
    WALLETTRANSACTION {
        int id PK
        int wallet_id FK
        int amount "fils, signed"
        string kind "topup, payment, refund"
        string reference
        datetime time
    }
    MENUITEM {
        int id PK
        string name
        int price "fils"
        int stock "CHECK >= 0"
        string tags
        bool available
    }
    ORDER {
        int id PK
        int customer_id FK
        datetime slot_start "UNIQUE with customer_id"
        string state
        int total "fils"
        string pickup_code
        datetime ready_at
        datetime closed_at
    }
    ORDERLINE {
        int id PK
        int order_id FK
        int item_id FK
        int quantity "CHECK 1 to 5"
        int price "unit price snapshot"
    }
    STRIKE {
        int id PK
        int user_id FK
        int order_id FK "UNIQUE"
        datetime time
    }
    AUDITENTRY {
        int id PK
        int actor_id FK
        string action
        string target
        datetime timestamp
    }
```

## 5. Order state machine

```mermaid
stateDiagram-v2
    [*] --> placed : customer places order (paid, stock reserved)
    placed --> cancelled : customer cancels until 15 min before slot, or kitchen withdraws an item
    placed --> preparing : kitchen starts
    preparing --> ready : kitchen marks ready, customer notified
    ready --> collected : counter checks 4-digit code
    ready --> uncollected : slot ended 20 min ago, no refund, strike
    cancelled --> [*]
    collected --> [*]
    uncollected --> [*]
```

## 6. Sequence: place an order (slot, stock, wallet checks)

```mermaid
sequenceDiagram
    actor C as Customer
    participant FE as Front end
    participant API as Back-end API
    participant DB as Database
    C->>FE: choose items and slot
    FE->>API: POST /orders (X-User-Email, slot_start, lines)
    API->>API: role is customer, slot on 15-min grid, 08:00-15:00, at least 20 min ahead, not blocked
    API->>DB: BEGIN
    API->>DB: count orders in slot (not cancelled)
    alt slot already has 20 orders
        API-->>FE: 409 Slot is full
    else customer already has an order in slot
        API-->>FE: 409 One order per slot
    else slot ok
        API->>DB: lock item rows in id order, check available and stock, decrement
        alt item unavailable or stock too low
            API->>DB: ROLLBACK
            API-->>FE: 409 Item unavailable
        else stock ok
            API->>DB: lock wallet row, check balance
            alt balance below total
                API->>DB: ROLLBACK
                API-->>FE: 402 Insufficient balance
            else balance ok
                API->>DB: debit wallet, insert payment ledger row, insert order, order lines, audit row
                API->>DB: COMMIT
                API-->>FE: 201 order id and total
            end
        end
    end
    FE-->>C: confirmation or error message
```

## 7. Sequence: counter pickup

```mermaid
sequenceDiagram
    actor C as Customer
    actor K as Kitchen
    actor S as Cashier
    participant API as Back-end API
    participant DB as Database
    participant N as E-mail and push
    K->>API: POST /orders/id/preparing
    API->>DB: placed to preparing, audit row
    K->>API: POST /orders/id/ready
    API->>DB: preparing to ready, ready_at, audit row
    API->>N: notify customer
    C->>API: GET /orders/mine
    API-->>C: pickup code (only when state is ready)
    C->>S: shows 4-digit code
    S->>API: POST /orders/id/pickup (code)
    API->>DB: lock order, state must be ready
    alt code does not match
        API-->>S: 403 Wrong pickup code
    else code matches
        API->>DB: ready to collected, closed_at, audit row
        API-->>S: 200 collected
    end
```

## 8. Sequence: uncollected-order job

```mermaid
sequenceDiagram
    participant T as Scheduler (every minute, 07:00-15:59)
    participant J as mark_uncollected_orders
    participant DB as Database
    T->>J: run
    J->>DB: BEGIN, lock ready orders with slot_start before now minus 35 min
    loop each overdue order
        J->>DB: state uncollected, closed_at, no refund
        J->>DB: insert Strike, audit row
        J->>DB: count strikes of this customer in last 30 days
        opt count is 3 or more and no block running
            J->>DB: set blocked_until to now plus 7 days
        end
    end
    J->>DB: COMMIT
    J-->>T: number of orders marked
```

## 9. Schedule: Gantt (PMP section 6)

```mermaid
gantt
    title CafeQuick schedule baseline (week 1 = 2026-10-05, placeholder date)
    dateFormat YYYY-MM-DD
    axisFormat %d %b
    section Critical path
    A Team, charter, working agreement (wk1-2)   :crit, a, 2026-10-05, 2026-10-19
    B Requirements and backlog (wk3-4)           :crit, b, 2026-10-19, 2026-11-02
    C Architecture and design baseline (wk5-6)   :crit, c, 2026-11-02, 2026-11-16
    E Environment, CI, Keycloak (wk7)            :crit, e, 2026-11-16, 2026-11-23
    Sprint 1 sign-in, menu, slots, ordering      :crit, s1, 2026-11-23, 2026-12-07
    Sprint 2 cancel, kitchen, pickup, top-up     :crit, s2, 2026-12-07, 2026-12-21
    Sprint 3 withdrawal, strikes, report, deploy :crit, s3, 2026-12-21, 2027-01-04
    F Final report and MVP freeze (wk14)         :crit, f, 2027-01-04, 2027-01-11
    section Parallel work
    D PMP sections 0-16 drafting (wk3-7)         :d, 2026-10-19, 2026-11-23
    Wireframes (wk5-6)                           :w, 2026-11-02, 2026-11-16
    Threat model and test plan (wk6-7)           :t, 2026-11-09, 2026-11-23
    PMP 17-20 and closure drafts (wk13-14)       :z, 2026-12-28, 2027-01-11
    section Milestones
    Week-7 checkpoint PMP 0-16                   :milestone, m7, 2026-11-23, 0d
    Presentation and online test (wk15)          :milestone, m15, 2027-01-18, 0d
```

## 10. Schedule: network and critical path (PMP section 6)

```mermaid
flowchart LR
    A["A Team and charter<br/>wk1-2"] --> B["B Requirements<br/>wk3-4"] --> C["C Architecture and design<br/>wk5-6"] --> E["E Environment, CI, Keycloak<br/>wk7"] --> S1["Sprint 1<br/>wk8-9"] --> S2["Sprint 2<br/>wk10-11"] --> S3["Sprint 3<br/>wk12-13"] --> F["F Final report, MVP freeze<br/>wk14"]
    B --> D["D PMP 0-16 drafting<br/>wk3-7"]
    D --> M7(["Week-7 checkpoint"])
    C --> W["Wireframes<br/>wk5-6"] --> S1
    C --> T["Threat model and test plan<br/>wk6-7"] --> S1
    S3 --> Z["PMP 17-20 drafts<br/>wk13-14"] --> F
    F --> P(["Presentation and online test<br/>wk15"])
    classDef crit stroke:#c0392b,stroke-width:3px
    class A,B,C,E,S1,S2,S3,F crit
```

## 11. Low-fidelity wireframes (five main screens)

These are the planned layouts from the brief. The built pages also have a sign-in and create-account screen (wireframe 6) and a customer wallet screen.

Screen 1: Customer, menu and order

```
+------------------------------------------+
| CafeQuick           student1@uni.edu  [x]|
+------------------------------------------+
| Menu                                     |
| [ ] Falafel Sandwich  1.000 JD  vegan    |
|     qty [-] 1 [+]     stock 58           |
| [ ] Chicken Shawarma  2.500 JD  halal    |
|     qty [-] 0 [+]     stock 40           |
| Allergens: gluten, dairy (tap item)      |
+------------------------------------------+
| Pickup slot:  ( ) 12:00  3 left          |
|               (x) 12:15  9 left          |
|               ( ) 12:30  full            |
+------------------------------------------+
| Total 1.000 JD   Wallet 49.000 JD        |
|            [ Place order ]               |
+------------------------------------------+
```

Screen 2: Customer, my orders

```
+------------------------------------------+
| My orders                                |
+------------------------------------------+
| #14  12:15   PLACED      1.000 JD        |
|      [ Cancel ]  (until 12:00)           |
| #12  11:45   READY       2.500 JD        |
|      PICKUP CODE:  4 8 2 1               |
| #09  yesterday  UNCOLLECTED  strike 1/3  |
+------------------------------------------+
```

Screen 3: Kitchen queue

```
+------------------------------------------+
| Kitchen queue                  Withdraw  |
+------------------------------------------+
| 12:00 slot                               |
|  #11  2x Shawarma, 1x Coffee             |
|       [ Preparing ]                      |
|  #12  1x Falafel     PREPARING           |
|       [ Ready ]                          |
| 12:15 slot                               |
|  #14  1x Falafel     [ Preparing ]       |
+------------------------------------------+
```

Screen 4: Cashier

```
+------------------------------------------+
| Cashier                                  |
+------------------------------------------+
| Pickup:  order # [ 12 ]  code [ ____ ]   |
|                       [ Hand over ]      |
+------------------------------------------+
| Top-up:  customer e-mail [____________]  |
|          amount (fils)   [______]        |
|                       [ Add to wallet ]  |
+------------------------------------------+
```

Screen 5: Manager, daily report

```
+------------------------------------------+
| Daily report      day [ 2026-11-09 ]     |
+------------------------------------------+
| Orders 4   Collected 1   Uncollected 1   |
| Cancelled 1          Revenue 8.600 JD    |
+------------------------------------------+
| Top items:  1 Falafel 4                  |
|             2 Shawarma 2                 |
|             3 Coffee 1                   |
+------------------------------------------+
| Menu and stock [ edit ]                  |
+------------------------------------------+
```

Screen 6: Customer, create account (added with the account pages)

```
+------------------------------------------+
| [ I have an account ] [ Create account ] |
+------------------------------------------+
| Create an account                        |
| Full name        [____________________]  |
| University e-mail [___________________]  |
| Starting wallet balance (JD) [ 10 ]      |
|   [ 5 JD ] [ 10 JD ] [ 20 JD ] [ 50 JD ] |
| Demo setting. Maximum 100 JD.            |
|            [ Create account ]            |
+------------------------------------------+
| Chef or cashier? Staff sign-in           |
+------------------------------------------+
```

## 12. Sequence: create account and sign in (accounts.py)

```mermaid
sequenceDiagram
    actor U as User
    participant FE as Front end
    participant API as Back-end API
    participant DB as Database
    U->>FE: choose Create an account, enter name, e-mail, starting balance
    FE->>API: POST /signup (name, email, initial_balance in fils)
    API->>API: e-mail not empty, balance 0 to 100000 fils, self-funding switch on
    API->>DB: BEGIN
    alt e-mail already has an account
        API->>DB: ROLLBACK
        API-->>FE: 409 This e-mail already has an account
    else new e-mail
        API->>DB: insert User with role customer, Wallet, opening top-up ledger row, audit row
        API->>DB: COMMIT
        API-->>FE: 201 created
        FE->>API: GET /me (X-User-Email)
        API->>DB: read user and wallet
        API-->>FE: name, role, balance
        FE-->>U: customer screens open, balance shown in the header
    end
```

## 13. Flow: which page and screens each role gets

```mermaid
flowchart LR
    ci["index.html<br/>customer page"] --> me["GET /me<br/>returns the role"]
    si["staff.html<br/>staff page"] --> me
    me -->|customer| cs["Order, My orders, Wallet"]
    me -->|kitchen| ks["Kitchen queue, withdraw an item"]
    me -->|cashier| cas["Hand over, wallet top-up"]
    me -->|manager| ms["Daily report, stock"]
    me -->|admin| ad["Audit log, run the job"]
    ci -.->|"staff account is refused"| me
    si -.->|"customer account is refused"| me
```
