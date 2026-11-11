from fastapi import FastAPI
from app.routers import eligibility, transcript

app = FastAPI()

#app.include_router(transcript.router)
app.include_router(eligibility.router) 
