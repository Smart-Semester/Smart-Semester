from fastapi import FastAPI
from routers import eligbility, transcript

app = FastAPI()

app.include_router(transcript.router)
app.include_router(eligbility.router) 
