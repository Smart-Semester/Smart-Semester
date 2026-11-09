from fastapi import FastAPI
from routers import eligibility, transcript

app = FastAPI()

app.include_router(transcript.router)
app.include_router(eligbility.router) 
