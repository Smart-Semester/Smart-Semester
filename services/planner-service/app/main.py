from fastapi import FastAPI
from app.routers import eligibility, transcript

app = FastAPI(title="Smart Semester Planner Service", version="0.1.0")

app.include_router(transcript.router)
app.include_router(eligibility.router)


@app.get("/health", tags=["ops"])
def health() -> dict:
    return {"status": "ok"}
