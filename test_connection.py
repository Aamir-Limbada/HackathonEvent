
import os
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

uri = os.getenv("MONGODB_URI")

if not uri:
    print("Could not find MONGODB_URI in .env")
else:
    try:
        client = MongoClient(uri, serverSelectionTimeoutMS=10000)
        client.admin.command("ping")
        print("Connected to MongoDB successfully!")
        client.close()
    except Exception as error:
        print("Connection failed:", error)
