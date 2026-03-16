import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

async def check():
    uri = 'mongodb+srv://admin:0vxvbiNXXSrtiL2r@purplemerit.8gmjowx.mongodb.net/?appName=PurpleMerit'
    client = AsyncIOMotorClient(uri)
    db = client['extractify']
    
    print("Connecting to MongoDB...")
    await client.admin.command('ping')
    print("Connected successfully.")
    
    collections = await db.list_collection_names()
    print("Collections in 'extractify' database:", collections)
    
    if 'reviews' in collections:
        reviews = await db['reviews'].find().to_list(100)
        print(f"Found {len(reviews)} reviews:")
        for r in reviews:
            print(" -", r)
    else:
        print("Collection 'reviews' not found.")
        
    client.close()

if __name__ == '__main__':
    asyncio.run(check())
