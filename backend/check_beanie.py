import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie, Document
from pydantic import Field
from datetime import datetime

class Review(Document):
    name: str
    email: str
    review_text: str
    rating: int
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "reviews"

async def check():
    uri = 'mongodb+srv://admin:0vxvbiNXXSrtiL2r@purplemerit.8gmjowx.mongodb.net/?appName=PurpleMerit'
    client = AsyncIOMotorClient(uri)
    db = client['extractify']
    
    await init_beanie(database=db, document_models=[Review])
    
    # Try an insert directly here!
    new_rev = Review(name="Test Beanie", email="b@b.com", review_text="beanie test", rating=5)
    await new_rev.insert()
    
    print("Inserted a review manually via beanie.")
    
    collections = await db.list_collection_names()
    print("Collections in 'extractify' database:", collections)
    
    reviews = await Review.find_all().to_list()
    print(f"Found {len(reviews)} reviews via Beanie: {reviews}")
        
    client.close()

if __name__ == '__main__':
    asyncio.run(check())
