import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers.auth import router as auth_router
from routers.capture import router as capture_router
from routers.games import router as games_router
from routers.admin import router as admin_router

app = FastAPI(title="Cowboy API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(games_router)
app.include_router(capture_router)
app.include_router(admin_router)


@app.get("/api/v1/health")
async def health():
    return {"status": "ok"}
