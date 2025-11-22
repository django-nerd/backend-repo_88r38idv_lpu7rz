"""
Database Schemas

Define your MongoDB collection schemas here using Pydantic models.
These schemas are used for data validation in your application.

Each Pydantic model represents a collection in your database.
Model name is converted to lowercase for the collection name:
- User -> "user" collection
- Product -> "product" collection
- BlogPost -> "blogs" collection
"""

from pydantic import BaseModel, Field, HttpUrl
from typing import Optional, List

# Domain Schemas for the Boss Encyclopedia

class Game(BaseModel):
    """
    Games collection schema
    Collection name: "game"
    """
    title: str = Field(..., description="Game title, e.g., 'Elden Ring'")
    platform: Optional[str] = Field(None, description="Platform or system, e.g., 'PC/PS5/Xbox'")
    cover_image: Optional[HttpUrl] = Field(None, description="URL to a cover image")
    description: Optional[str] = Field(None, description="Short description of the game")

class Boss(BaseModel):
    """
    Bosses collection schema
    Collection name: "boss"
    """
    game_id: str = Field(..., description="Reference to the game document _id as string")
    name: str = Field(..., description="Boss name")
    image: Optional[HttpUrl] = Field(None, description="Primary image URL of the boss")
    summary: Optional[str] = Field(None, description="Short lore/overview")
    difficulty: Optional[str] = Field(None, description="Relative difficulty label")

class Strategy(BaseModel):
    """
    Strategies collection schema
    Collection name: "strategy"
    """
    boss_id: str = Field(..., description="Reference to the boss document _id as string")
    title: str = Field(..., description="Strategy title, e.g., 'Melee build cheese' ")
    steps: List[str] = Field(default_factory=list, description="Ordered bullet points with steps")
    recommended_level: Optional[str] = Field(None, description="Recommended level/gear")
    video_url: Optional[HttpUrl] = Field(None, description="YouTube or other video URL")

# Example schemas kept for reference (not used by the app but safe to keep if needed)
class User(BaseModel):
    name: str
    email: str
    address: str
    age: Optional[int] = None
    is_active: bool = True

class Product(BaseModel):
    title: str
    description: Optional[str] = None
    price: float
    category: str
    in_stock: bool = True
