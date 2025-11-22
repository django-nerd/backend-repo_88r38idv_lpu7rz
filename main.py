import os
from fastapi import FastAPI, HTTPException, Query, Path, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, HttpUrl
from typing import List, Optional
from bson import ObjectId

from database import db, create_document, get_documents

app = FastAPI(title="Boss Encyclopedia API", version="1.3.0")

# CORS: allow the frontend URL if provided; if wildcard, don't allow credentials to satisfy browser rules
frontend_origin = os.getenv("FRONTEND_URL", "*")
allow_all = frontend_origin == "*"
app.add_middleware(
    CORSMiddleware,
    allow_origins=[frontend_origin] if not allow_all else ["*"],
    allow_credentials=not allow_all,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"]
)

# Security headers middleware (basic hardening)
CSP = (
    "default-src 'self'; "
    "base-uri 'self'; "
    "img-src 'self' data: https:; "
    "style-src 'self' 'unsafe-inline' https:; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval' https:; "
    "font-src 'self' https: data:; "
    "frame-src 'self' https://www.youtube.com https://youtube.com https://player.vimeo.com; "
    "connect-src 'self' *;"
)

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response: Response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
    response.headers.setdefault("Content-Security-Policy", CSP)
    return response

# Helpers
class ObjectIdStr(str):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if isinstance(v, ObjectId):
            return str(v)
        if not isinstance(v, str):
            raise TypeError("ObjectId must be a string")
        return v

def serialize_doc(doc: dict) -> dict:
    if not doc:
        return doc
    d = dict(doc)
    _id = d.get("_id")
    if isinstance(_id, ObjectId):
        d["id"] = str(_id)
    elif isinstance(_id, str):
        d["id"] = _id
    d.pop("_id", None)
    for k, v in list(d.items()):
        if isinstance(v, ObjectId):
            d[k] = str(v)
    return d

# Request/Response models
class GameCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    platform: Optional[str] = Field(None, max_length=120)
    cover_image: Optional[HttpUrl | str] = Field(None)
    description: Optional[str] = Field(None, max_length=2000)

class GameOut(GameCreate):
    id: ObjectIdStr

class BossCreate(BaseModel):
    game_id: str = Field(..., description="Game document id as string")
    name: str = Field(..., min_length=1, max_length=160)
    image: Optional[HttpUrl | str] = None
    summary: Optional[str] = Field(None, max_length=2000)
    difficulty: Optional[str] = Field(None, max_length=50)

class BossOut(BossCreate):
    id: ObjectIdStr

class StrategyCreate(BaseModel):
    boss_id: str
    title: str
    steps: List[str] = []
    recommended_level: Optional[str] = None
    video_url: Optional[HttpUrl | str] = None

class StrategyOut(StrategyCreate):
    id: ObjectIdStr

# Ingestion schemas
class YouTubeIngest(BaseModel):
    game_title: str = Field(..., min_length=1, max_length=120)
    boss_name: str = Field(..., min_length=1, max_length=160)
    video_url: HttpUrl
    strategy_title: Optional[str] = Field(None, max_length=160)
    steps: List[str] = []
    recommended_level: Optional[str] = None
    image: Optional[HttpUrl | str] = None
    summary: Optional[str] = None
    difficulty: Optional[str] = None

class BulkBoss(BaseModel):
    name: str
    image: Optional[HttpUrl | str] = None
    summary: Optional[str] = None
    difficulty: Optional[str] = None
    strategies: List[StrategyCreate] = []

class BulkIngest(BaseModel):
    game_title: str
    platform: Optional[str] = None
    cover_image: Optional[HttpUrl | str] = None
    description: Optional[str] = None
    bosses: List[BulkBoss] = []

# Moderation queue schemas
class QueueItem(BaseModel):
    source: str = Field(..., description="Source identifier, e.g., 'youtube', 'wiki'")
    game_title: str
    boss_name: str
    strategy_title: Optional[str] = None
    steps: List[str] = []
    recommended_level: Optional[str] = None
    video_url: Optional[HttpUrl | str] = None
    image: Optional[HttpUrl | str] = None
    summary: Optional[str] = None
    difficulty: Optional[str] = None
    status: str = Field(default="pending", description="pending|approved|rejected")

class QueueUpdate(BaseModel):
    status: str = Field(..., pattern="^(pending|approved|rejected)$")

# Routes
@app.get("/")
def read_root():
    return {"message": "Boss Encyclopedia API is running"}

@app.get("/test")
def test_database():
    """Test endpoint to check if database is available and accessible"""
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }

    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"
    return response

# Games
@app.post("/api/games", response_model=GameOut)
def create_game(game: GameCreate):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    doc_id = create_document("game", game.model_dump())
    created = db["game"].find_one({"_id": ObjectId(doc_id)})
    return serialize_doc(created)

@app.get("/api/games", response_model=List[GameOut])
def list_games():
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    items = get_documents("game", {})
    return [serialize_doc(d) for d in items]

# Bosses
@app.post("/api/bosses", response_model=BossOut)
def create_boss(boss: BossCreate):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    # validate game exists
    try:
        gid = ObjectId(boss.game_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid game_id")
    if db["game"].count_documents({"_id": gid}, limit=1) == 0:
        raise HTTPException(status_code=404, detail="Game not found")
    doc_id = create_document("boss", boss.model_dump())
    created = db["boss"].find_one({"_id": ObjectId(doc_id)})
    return serialize_doc(created)

@app.get("/api/bosses", response_model=List[BossOut])
def list_bosses(
    game_id: Optional[str] = None,
    q: Optional[str] = Query(None, min_length=1, max_length=120),
    skip: int = Query(0, ge=0, le=10000),
    limit: int = Query(50, ge=1, le=100),
):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    filter_dict = {}
    if game_id:
        try:
            filter_dict["game_id"] = str(ObjectId(game_id))
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid game_id")
    if q:
        filter_dict["name"] = {"$regex": q, "$options": "i"}
    cursor = db["boss"].find(filter_dict).skip(skip).limit(limit)
    items = list(cursor)
    return [serialize_doc(d) for d in items]

@app.get("/api/bosses/{boss_id}")
def get_boss_detail(boss_id: str = Path(..., min_length=8, max_length=64)):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    try:
        _id = ObjectId(boss_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid boss id")
    boss = db["boss"].find_one({"_id": _id})
    if not boss:
        raise HTTPException(status_code=404, detail="Boss not found")
    boss_out = serialize_doc(boss)
    strategies = get_documents("strategy", {"boss_id": boss_out["id"]})
    boss_out["strategies"] = [serialize_doc(s) for s in strategies]
    return boss_out

# Strategies
@app.post("/api/strategies", response_model=StrategyOut)
def create_strategy(strategy: StrategyCreate):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    # validate boss exists
    try:
        bid = ObjectId(strategy.boss_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid boss_id")
    if db["boss"].count_documents({"_id": bid}, limit=1) == 0:
        raise HTTPException(status_code=404, detail="Boss not found")
    # dedupe by video_url if provided
    if strategy.video_url:
        existing = db["strategy"].find_one({"boss_id": strategy.boss_id, "video_url": str(strategy.video_url)})
        if existing:
            return serialize_doc(existing)
    doc_id = create_document("strategy", strategy.model_dump())
    created = db["strategy"].find_one({"_id": ObjectId(doc_id)})
    return serialize_doc(created)

@app.get("/api/strategies", response_model=List[StrategyOut])
def list_strategies(boss_id: str):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    try:
        _ = ObjectId(boss_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid boss_id")
    items = get_documents("strategy", {"boss_id": boss_id})
    return [serialize_doc(d) for d in items]

# Automation: demo ingestion to populate with sample data
@app.post("/api/ingest/demo")
def ingest_demo():
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")

    # If already populated, skip
    if db["game"].count_documents({"title": "Elden Ring"}, limit=1) > 0:
        game_doc = db["game"].find_one({"title": "Elden Ring"})
        return serialize_doc(game_doc)

    # create game
    game = GameCreate(
        title="Elden Ring",
        platform="PC/PS5/Xbox",
        cover_image="https://images.igdb.com/igdb/image/upload/t_cover_big/co4jni.jpg",
        description="Open-world action RPG by FromSoftware featuring challenging boss fights."
    )
    game_id = create_document("game", game.model_dump())

    bosses = [
        {
            "name": "Margit, the Fell Omen",
            "image": "https://static.wikia.nocookie.net/eldenring/images/4/4b/Margit_the_Fell_Omen.jpg",
            "summary": "Gatekeeper of Stormveil Castle with punishing combos and holy daggers.",
            "difficulty": "Hard"
        },
        {
            "name": "Godrick the Grafted",
            "image": "https://static.wikia.nocookie.net/eldenring/images/4/41/Godrick_the_Grafted.jpg",
            "summary": "Demigod who commands storm and grafted limbs.",
            "difficulty": "Hard"
        },
        {
            "name": "Malenia, Blade of Miquella",
            "image": "https://static.wikia.nocookie.net/eldenring/images/a/aa/Malenia_Blade_of_Miquella.jpg",
            "summary": "Infamous duel with lifesteal and Waterfowl Dance.",
            "difficulty": "Legendary"
        }
    ]

    for b in bosses:
        bdoc = BossCreate(game_id=str(ObjectId(game_id)), **b)
        bid = create_document("boss", bdoc.model_dump())
        # simple strategy per boss
        if bdoc.name.startswith("Margit"):
            steps = [
                "Summon Spirit Ashes to draw aggro.",
                "Bait the dagger throw then roll forward.",
                "Punish slow hammer slam with 1-2 hits.",
            ]
            video = "https://www.youtube.com/embed/IfZk96F6eAQ"
        elif bdoc.name.startswith("Godrick"):
            steps = [
                "Stay mid-range to bait whirlwind.",
                "In phase 2, avoid dragon flame then circle to his left.",
                "Use bleed or frost for faster stagger.",
            ]
            video = "https://www.youtube.com/embed/Goe7bD8Jo1Q"
        else:
            steps = [
                "Use lightweight roll setup for iframes.",
                "When she hops, sprint away to dodge Waterfowl Dance.",
                "Inflict Scarlet Rot or Bleed to wear her down.",
            ]
            video = "https://www.youtube.com/embed/Hgfbm9lY0AU"
        sdoc = StrategyCreate(boss_id=str(ObjectId(bid)), title=f"How to beat {bdoc.name}", steps=steps, recommended_level="80+", video_url=video)
        # dedupe strategy per video
        if db["strategy"].count_documents({"boss_id": sdoc.boss_id, "video_url": sdoc.video_url}, limit=1) == 0:
            create_document("strategy", sdoc.model_dump())

    created_game = db["game"].find_one({"_id": ObjectId(game_id)})
    return serialize_doc(created_game)

# Automation: lightweight ingestion helpers
@app.post("/api/ingest/youtube")
def ingest_youtube(data: YouTubeIngest):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")

    # ensure game
    game = db["game"].find_one({"title": data.game_title})
    if not game:
        game_create = GameCreate(title=data.game_title)
        game_id = create_document("game", game_create.model_dump())
        game = db["game"].find_one({"_id": ObjectId(game_id)})
    game_id_str = str(game["_id"]) if isinstance(game["_id"], ObjectId) else game.get("id")

    # ensure boss
    boss = db["boss"].find_one({"name": data.boss_name, "game_id": game_id_str})
    if not boss:
        new_boss = BossCreate(
            game_id=game_id_str,
            name=data.boss_name,
            image=data.image,
            summary=data.summary,
            difficulty=data.difficulty,
        )
        boss_id = create_document("boss", new_boss.model_dump())
        boss = db["boss"].find_one({"_id": ObjectId(boss_id)})

    # create strategy with dedupe on video_url
    strategy = StrategyCreate(
        boss_id=str(boss["_id"]) if isinstance(boss["_id"], ObjectId) else boss.get("id"),
        title=data.strategy_title or f"Video Guide: {data.boss_name}",
        steps=data.steps or [],
        recommended_level=data.recommended_level,
        video_url=str(data.video_url),
    )
    existing = db["strategy"].find_one({"boss_id": strategy.boss_id, "video_url": strategy.video_url})
    if existing:
        return serialize_doc(existing)
    sid = create_document("strategy", strategy.model_dump())
    created = db["strategy"].find_one({"_id": ObjectId(sid)})
    return serialize_doc(created)

@app.post("/api/ingest/bulk")
def ingest_bulk(payload: BulkIngest):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")

    # ensure game
    game = db["game"].find_one({"title": payload.game_title})
    if not game:
        game_create = GameCreate(
            title=payload.game_title,
            platform=payload.platform,
            cover_image=payload.cover_image,
            description=payload.description,
        )
        game_id = create_document("game", game_create.model_dump())
        game = db["game"].find_one({"_id": ObjectId(game_id)})
    game_id_str = str(game["_id"]) if isinstance(game["_id"], ObjectId) else game.get("id")

    created_bosses: List[dict] = []
    for b in payload.bosses:
        boss = db["boss"].find_one({"name": b.name, "game_id": game_id_str})
        if not boss:
            boss_create = BossCreate(
                game_id=game_id_str,
                name=b.name,
                image=b.image,
                summary=b.summary,
                difficulty=b.difficulty,
            )
            bid = create_document("boss", boss_create.model_dump())
            boss = db["boss"].find_one({"_id": ObjectId(bid)})
        # strategies with dedupe by video_url
        for s in b.strategies:
            try:
                # validate boss id
                _ = ObjectId(s.boss_id)
                if s.video_url and db["strategy"].count_documents({"boss_id": s.boss_id, "video_url": s.video_url}, limit=1) > 0:
                    continue
                sid = create_document("strategy", s.model_dump())
                _ = db["strategy"].find_one({"_id": ObjectId(sid)})
            except Exception:
                # if provided boss_id is invalid or missing, force link to created boss
                link_boss_id = str(boss["_id"]) if isinstance(boss["_id"], ObjectId) else boss.get("id")
                if s.video_url and db["strategy"].count_documents({"boss_id": link_boss_id, "video_url": s.video_url}, limit=1) > 0:
                    continue
                strategy = StrategyCreate(
                    boss_id=link_boss_id,
                    title=s.title,
                    steps=s.steps,
                    recommended_level=s.recommended_level,
                    video_url=s.video_url,
                )
                sid = create_document("strategy", strategy.model_dump())
                _ = db["strategy"].find_one({"_id": ObjectId(sid)})
        created_bosses.append(serialize_doc(boss))

    return {"game": serialize_doc(game), "bosses": created_bosses}

# Moderation & dedupe pipeline
@app.post("/api/mod/submit", summary="Submit external item to moderation queue")
def mod_submit(item: QueueItem):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    # dedupe in queue by source+video or source+boss_name
    q = {"source": item.source, "game_title": item.game_title, "boss_name": item.boss_name}
    if item.video_url:
        q["video_url"] = str(item.video_url)
    existing = db["ingest_queue"].find_one(q)
    if existing:
        return serialize_doc(existing)
    _id = create_document("ingest_queue", item.model_dump())
    created = db["ingest_queue"].find_one({"_id": ObjectId(_id)})
    return serialize_doc(created)

@app.get("/api/mod/queue", summary="List moderation queue items")
def mod_queue(status: str = Query("pending")):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    items = get_documents("ingest_queue", {"status": status})
    return [serialize_doc(x) for x in items]

@app.post("/api/mod/approve/{item_id}", summary="Approve queue item and ingest")
def mod_approve(item_id: str):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    try:
        oid = ObjectId(item_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")
    item = db["ingest_queue"].find_one({"_id": oid})
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    # ensure game
    game = db["game"].find_one({"title": item.get("game_title")})
    if not game:
        game_id = create_document("game", GameCreate(title=item.get("game_title")).model_dump())
        game = db["game"].find_one({"_id": ObjectId(game_id)})
    game_id_str = str(game["_id"]) if isinstance(game["_id"], ObjectId) else game.get("id")

    # ensure boss
    boss = db["boss"].find_one({"name": item.get("boss_name"), "game_id": game_id_str})
    if not boss:
        bid = create_document("boss", BossCreate(game_id=game_id_str, name=item.get("boss_name"), image=item.get("image"), summary=item.get("summary"), difficulty=item.get("difficulty")).model_dump())
        boss = db["boss"].find_one({"_id": ObjectId(bid)})

    # create strategy if supplied (dedupe by video_url)
    vid = item.get("video_url")
    if vid:
        link_boss_id = str(boss["_id"]) if isinstance(boss["_id"], ObjectId) else boss.get("id")
        exists = db["strategy"].find_one({"boss_id": link_boss_id, "video_url": vid})
        if not exists:
            sid = create_document("strategy", StrategyCreate(boss_id=link_boss_id, title=item.get("strategy_title") or f"Guide: {item.get('boss_name')}", steps=item.get("steps") or [], recommended_level=item.get("recommended_level"), video_url=vid).model_dump())
            _ = db["strategy"].find_one({"_id": ObjectId(sid)})

    # mark approved
    db["ingest_queue"].update_one({"_id": oid}, {"$set": {"status": "approved"}})
    item = db["ingest_queue"].find_one({"_id": oid})
    return serialize_doc(item)

@app.post("/api/mod/reject/{item_id}", summary="Reject queue item")
def mod_reject(item_id: str):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    try:
        oid = ObjectId(item_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")
    r = db["ingest_queue"].update_one({"_id": oid}, {"$set": {"status": "rejected"}})
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Item not found")
    item = db["ingest_queue"].find_one({"_id": oid})
    return serialize_doc(item)

# A manual trigger for scheduled ingestion of curated sources (safe, no external calls here)
@app.post("/api/ingest/scheduled-run", summary="Simulate scheduled crawl and add items to moderation queue")
def scheduled_ingest():
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    samples = [
        QueueItem(source="youtube", game_title="Elden Ring", boss_name="Radahn, Starscourge", strategy_title="Bleed Build", steps=["Use Rivers of Blood", "Stay on horseback"], video_url="https://www.youtube.com/embed/sample123", image=None, summary="Festival of Radahn fight", difficulty="Hard").model_dump(),
        QueueItem(source="wiki", game_title="Sekiro", boss_name="Genichiro Ashina", strategy_title="Mikiri + Deflect", steps=["Bait thrust for Mikiri", "Deflect bow combos"], video_url=None, image=None, summary="Castle rooftop duel", difficulty="Hard").model_dump(),
    ]
    inserted = []
    for s in samples:
        q = {"source": s["source"], "game_title": s["game_title"], "boss_name": s["boss_name"]}
        if s.get("video_url"):
            q["video_url"] = s["video_url"]
        existing = db["ingest_queue"].find_one(q)
        if existing:
            inserted.append(serialize_doc(existing))
            continue
        _id = create_document("ingest_queue", s)
        created = db["ingest_queue"].find_one({"_id": ObjectId(_id)})
        inserted.append(serialize_doc(created))
    return {"queued": inserted}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
