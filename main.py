import os
from fastapi import FastAPI, HTTPException, Query, Path
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional
from bson import ObjectId

from database import db, create_document, get_documents

app = FastAPI(title="Boss Encyclopedia API", version="1.0.0")

# CORS: allow the frontend URL if provided, otherwise allow all (dev)
frontend_origin = os.getenv("FRONTEND_URL", "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[frontend_origin] if frontend_origin != "*" else ["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

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
    cover_image: Optional[str] = Field(None)
    description: Optional[str] = Field(None, max_length=2000)

class GameOut(GameCreate):
    id: ObjectIdStr

class BossCreate(BaseModel):
    game_id: str = Field(..., description="Game document id as string")
    name: str = Field(..., min_length=1, max_length=160)
    image: Optional[str] = None
    summary: Optional[str] = Field(None, max_length=2000)
    difficulty: Optional[str] = Field(None, max_length=50)

class BossOut(BossCreate):
    id: ObjectIdStr

class StrategyCreate(BaseModel):
    boss_id: str
    title: str
    steps: List[str] = []
    recommended_level: Optional[str] = None
    video_url: Optional[str] = None

class StrategyOut(StrategyCreate):
    id: ObjectIdStr

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
def list_bosses(game_id: Optional[str] = None, q: Optional[str] = Query(None, min_length=1, max_length=120)):
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
    items = get_documents("boss", filter_dict)
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
        create_document("strategy", sdoc.model_dump())

    created_game = db["game"].find_one({"_id": ObjectId(game_id)})
    return serialize_doc(created_game)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
