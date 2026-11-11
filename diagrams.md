# CafeQuick diagrams (PMP section 5 and 6)

Mermaid source. GitHub renders these blocks directly. To get images for the PDF, paste a block into
https://mermaid.live and export PNG/SVG (check it is readable when printed, as the brief requires).
Status: written from the brief and the current code; not yet reviewed by the team.

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
        fe["Front end<br/>HTML, JavaScript or React<br/>static files over HTTPS"]
        api["Back-end API<br/>Python FastAPI modular monolith<br/>owns slot, stock, wallet, cancel, pickup rules"]
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
