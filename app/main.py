import os
from fastapi import FastAPI, Depends, Header, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from fastapi import Form, Query
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import text

DB_URL = os.environ["DB_URL"]
engine = create_async_engine(DB_URL, pool_pre_ping=True)
Session = async_sessionmaker(engine, expire_on_commit=False)

app = FastAPI(title="Inventory API")

# Resolve the static dir relative to this file so it works in Docker
BASE_DIR = os.path.dirname(__file__)
STATIC_DIR = os.path.join(BASE_DIR, "static")

# Serve UI at /ui and redirect / -> /ui
app.mount("/ui", StaticFiles(directory=STATIC_DIR, html=True), name="ui")
# If your HTML references /static/... assets, also expose this:
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/")
async def root():
    return RedirectResponse(url="/ui")

# --- simple RBAC via headers for now ---
def require_role(*allowed):
    async def _dep(x_user_role: str | None = Header(None)):
        if x_user_role is None or x_user_role not in allowed:
            raise HTTPException(status_code=403, detail="Forbidden")
    return _dep

async def get_session() -> AsyncSession:
    async with Session() as s:
        yield s

@app.get("/health")
async def health():
    return {"ok": True}

# ------- Parts listing (alphanumeric sorted one row per part) -------
@app.get("/parts")
async def parts(search: str = "", session: AsyncSession = Depends(get_session)):
    q = """
    SELECT pc.part_no, pc.description, COALESCE(i.qty_on_hand,0) AS available, COALESCE(i.location,'') AS location
    FROM parts_catalog pc
    LEFT JOIN inventory i ON i.part_no = pc.part_no
    WHERE pc.active = TRUE
      AND (pc.part_no ILIKE :s OR pc.description ILIKE :s)
    ORDER BY pc.part_no ASC
    """
    rows = (await session.execute(text(q), {"s": f"%{search}%"})).mappings().all()
    return list(rows)

# ------- Read-only stock snapshot -------
@app.get("/stock", dependencies=[Depends(require_role("PartsAdmin","InventoryAdmin"))])
async def stock(search: str = "", session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(text("""
      SELECT pc.part_no, pc.description, COALESCE(i.qty_on_hand,0) AS available, COALESCE(i.location,'') AS location
      FROM parts_catalog pc
      LEFT JOIN inventory i ON i.part_no = pc.part_no
      WHERE pc.active = TRUE
        AND (pc.part_no ILIKE :s OR pc.description ILIKE :s)
      ORDER BY pc.part_no ASC
    """), {"s": f"%{search}%"})).mappings().all()
    return list(rows)

# ------- Ledger (paged, filtered) -------
@app.get("/ledger", dependencies=[Depends(require_role("InventoryAdmin","PartsAdmin"))])
async def ledger(
    action: str | None = None,        # 'checkout' or 'checkin' or None
    part_no: str | None = None,
    work_order_no: str | None = None,
    since: str | None = None,         # ISO date or datetime
    until: str | None = None,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
):
    where = ["1=1"]
    params = {}
    if action:
        where.append("l.action = :action")
        params["action"] = action
    if part_no:
        where.append("l.part_no ILIKE :p")
        params["p"] = part_no
    if work_order_no:
        where.append("l.work_order_no ILIKE :wo")
        params["wo"] = work_order_no
    if since:
        where.append("l.event_time >= :since")
        params["since"] = since
    if until:
        where.append("l.event_time <= :until")
        params["until"] = until

    q = f"""
      SELECT l.event_time, u.upn AS user_upn, l.action, l.part_no, l.qty, l.work_order_no,
             l.vendor_claim_no, l.prev_qty, l.new_qty
      FROM ledger l
      LEFT JOIN users u ON u.id = l.user_id
      WHERE {' AND '.join(where)}
      ORDER BY l.event_time DESC
      LIMIT :limit OFFSET :offset
    """
    params["limit"] = max(1, min(limit, 500))
    params["offset"] = max(0, offset)

    rows = (await session.execute(text(q), params)).mappings().all()
    return list(rows)

# ------- Cart helpers -------
@app.post("/cart", dependencies=[Depends(require_role("PartsAdmin","InventoryAdmin"))])
async def get_or_create_cart(x_user_upn: str | None = Header(None),
                             session: AsyncSession = Depends(get_session)):
    if not x_user_upn: raise HTTPException(401, "Missing user")
    await session.execute(text("""
        INSERT INTO users(upn)
        VALUES (:u)
        ON CONFLICT (upn) DO NOTHING
    """), {"u": x_user_upn})
    res = await session.execute(text("""
        SELECT id FROM checkout_cart WHERE user_id=(SELECT id FROM users WHERE upn=:u)
        ORDER BY created_at DESC LIMIT 1
    """), {"u": x_user_upn})
    row = res.first()
    if row:
        await session.commit()
        return {"cart_id": row[0]}
    new = await session.execute(text("""
        INSERT INTO checkout_cart(user_id)
        VALUES ((SELECT id FROM users WHERE upn=:u)) RETURNING id
    """), {"u": x_user_upn})
    cid = new.first()[0]
    await session.commit()
    return {"cart_id": cid}

@app.post("/cart/lines", dependencies=[Depends(require_role("PartsAdmin","InventoryAdmin"))])
async def add_line(part_no: str,
                   x_user_upn: str | None = Header(None),
                   session: AsyncSession = Depends(get_session)):
    if not x_user_upn: raise HTTPException(401, "Missing user")
    async with session.begin():
        cart = await session.execute(text("""
          SELECT id FROM checkout_cart WHERE user_id=(SELECT id FROM users WHERE upn=:u)
          ORDER BY created_at DESC LIMIT 1
        """), {"u": x_user_upn})
        c = cart.first()
        if not c: raise HTTPException(400, "Cart not found; create /cart")
        await session.execute(text("""
          INSERT INTO checkout_cart_lines(cart_id, part_no, qty) VALUES (:c, :p, 1)
        """), {"c": c[0], "p": part_no})
    return {"ok": True}

@app.get("/cart/summary", dependencies=[Depends(require_role("PartsAdmin","InventoryAdmin"))])
async def cart_summary(x_user_upn: str | None = Header(None),
                       session: AsyncSession = Depends(get_session)):
    if not x_user_upn: raise HTTPException(401, "Missing user")
    rows = (await session.execute(text("""
      SELECT l.part_no, 1 AS qty
      FROM checkout_cart_lines l
      JOIN checkout_cart c ON c.id = l.cart_id
      WHERE c.user_id = (SELECT id FROM users WHERE upn=:u)
      ORDER BY l.part_no ASC
    """), {"u": x_user_upn})).mappings().all()
    return list(rows)

@app.delete("/cart/clear", dependencies=[Depends(require_role("PartsAdmin","InventoryAdmin"))])
async def cart_clear(
    x_user_upn: str | None = Header(None),
    session: AsyncSession = Depends(get_session),
):
    if not x_user_upn:
        raise HTTPException(401, "Missing user")
    async with session.begin():
        await session.execute(text("""
          DELETE FROM checkout_cart_lines
          WHERE cart_id IN (
            SELECT id FROM checkout_cart
            WHERE user_id = (SELECT id FROM users WHERE upn=:u)
          )
        """), {"u": x_user_upn})
    return {"ok": True}

# ------- Checkout commit (atomic, outbound qty always 1) -------
@app.post("/checkout/commit", dependencies=[Depends(require_role("PartsAdmin","InventoryAdmin"))])
async def checkout_commit(
    request: Request,
    work_order_no: str | None = Query(None),
    work_order_no_form: str | None = Form(None),
    x_user_upn: str | None = Header(None),
    session: AsyncSession = Depends(get_session),
):
    if not x_user_upn:
        raise HTTPException(401, "Missing user")

    # Accept WO from query OR form, with a raw-form fallback
    try:
        raw_form = await request.form()
    except Exception:
        raw_form = {}
    wo = (work_order_no or work_order_no_form or (raw_form.get("work_order_no") if raw_form else None) or "").strip()
    if not wo:
        raise HTTPException(status_code=422, detail="work_order_no is required")

    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent","")

    async with session.begin():
        # ensure work order exists
        await session.execute(text("""
          INSERT INTO work_orders(work_order_no) VALUES (:wo)
          ON CONFLICT (work_order_no) DO NOTHING
        """), {"wo": wo})

        # get the current user's cart lines
        lines = (await session.execute(text("""
          SELECT l.part_no FROM checkout_cart_lines l
          JOIN checkout_cart c ON c.id = l.cart_id
          WHERE c.user_id = (SELECT id FROM users WHERE upn=:u)
          ORDER BY l.part_no ASC
        """), {"u": x_user_upn})).scalars().all()
        if not lines:
            raise HTTPException(400, "Cart is empty")

        for part_no in lines:
            row = (await session.execute(text(
                "SELECT qty_on_hand FROM inventory WHERE part_no=:p FOR UPDATE"
            ), {"p": part_no})).first()
            prev = row[0] if row else 0
            if prev < 1:
                raise HTTPException(status_code=409, detail=f"{part_no} out of stock")

            # decrement stock
            await session.execute(text(
                "UPDATE inventory SET qty_on_hand=qty_on_hand-1, updated_at=now() WHERE part_no=:p"
            ), {"p": part_no})

            # transaction & ledger
            await session.execute(text("""
              INSERT INTO transactions(type, part_no, qty, work_order_no, user_id)
              VALUES ('checkout', :p, 1, :wo, (SELECT id FROM users WHERE upn=:u))
            """), {"p": part_no, "wo": wo, "u": x_user_upn})

            await session.execute(text("""
              INSERT INTO ledger(event_time, user_id, action, part_no, qty, work_order_no, ip, user_agent, prev_qty, new_qty)
              VALUES (now(), (SELECT id FROM users WHERE upn=:u), 'checkout', :p, 1, :wo, :ip, :ua, :prev, :new)
            """), {"u": x_user_upn, "p": part_no, "wo": wo, "ip": ip, "ua": ua, "prev": prev, "new": prev-1})

        # clear the cart
        await session.execute(text("""
          DELETE FROM checkout_cart_lines
          WHERE cart_id IN (SELECT id FROM checkout_cart WHERE user_id=(SELECT id FROM users WHERE upn=:u))
        """), {"u": x_user_upn})

    return {"ok": True, "work_order_no": wo}

# ------- Receiving (check-in) -------
@app.post("/checkin", dependencies=[Depends(require_role("PartsAdmin","InventoryAdmin"))])
async def checkin(
    request: Request,
    part_no: str | None = Query(None),
    work_order_no: str | None = Query(None),
    vendor_claim_no: str | None = Query(None),
    part_no_form: str | None = Form(None),
    work_order_no_form: str | None = Form(None),
    vendor_claim_no_form: str | None = Form(None),
    x_user_upn: str | None = Header(None),
    session: AsyncSession = Depends(get_session),
):
    if not x_user_upn:
        raise HTTPException(401, "Missing user")

    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent","")

    # Accept from query OR form; also try raw form for maximum compatibility
    try:
        raw_form = await request.form()
    except Exception:
        raw_form = {}

    pn = (part_no or part_no_form or (raw_form.get("part_no") if raw_form else None) or "").strip()
    wo = (work_order_no or work_order_no_form or (raw_form.get("work_order_no") if raw_form else None) or "").strip()
    vc = (vendor_claim_no or vendor_claim_no_form or (raw_form.get("vendor_claim_no") if raw_form else None) or "").strip()

    if not pn or not wo or not vc:
        raise HTTPException(status_code=422, detail="part_no, work_order_no, vendor_claim_no are required")

    async with session.begin():
        # ensure the part exists in the catalog (seamless first-time check-in)
        await session.execute(text("""
          INSERT INTO parts_catalog(part_no, description, active)
          VALUES (:p, 'Uncatalogued', TRUE)
          ON CONFLICT (part_no) DO NOTHING
        """), {"p": pn})

        # ensure the work order exists
        await session.execute(text("""
          INSERT INTO work_orders(work_order_no) VALUES (:wo)
          ON CONFLICT (work_order_no) DO NOTHING
        """), {"wo": wo})

        # lock + increment inventory
        row = (await session.execute(text(
          "SELECT qty_on_hand FROM inventory WHERE part_no=:p FOR UPDATE"
        ), {"p": pn})).first()
        if row is None:
            await session.execute(text(
                "INSERT INTO inventory(part_no, qty_on_hand) VALUES (:p, 0)"
            ), {"p": pn})
            prev = 0
        else:
            prev = row[0]

        await session.execute(text(
          "UPDATE inventory SET qty_on_hand=qty_on_hand+1, updated_at=now() WHERE part_no=:p"
        ), {"p": pn})

        # transaction & ledger
        await session.execute(text("""
          INSERT INTO transactions(type, part_no, qty, work_order_no, vendor_claim_no, user_id)
          VALUES ('checkin', :p, 1, :wo, :vc, (SELECT id FROM users WHERE upn=:u))
        """), {"p": pn, "wo": wo, "vc": vc, "u": x_user_upn})

        await session.execute(text("""
          INSERT INTO ledger(event_time, user_id, action, part_no, qty, work_order_no, vendor_claim_no, ip, user_agent, prev_qty, new_qty)
          VALUES (now(), (SELECT id FROM users WHERE upn=:u), 'checkin', :p, 1, :wo, :vc, :ip, :ua, :prev, :new)
        """), {"u": x_user_upn, "p": pn, "wo": wo, "vc": vc, "ip": ip, "ua": ua, "prev": prev, "new": prev+1})

    return {"ok": True}

