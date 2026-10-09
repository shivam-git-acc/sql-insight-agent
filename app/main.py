from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import agent

STATIC = Path(__file__).parent / "static"

app = FastAPI(title="SQL Insight Agent")
app.mount("/static", StaticFiles(directory=STATIC), name="static")

# The page loads only its own files, so a strict policy is possible:
# no third-party scripts, no inline scripts, no framing by other sites.
PAGE_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


class AskRequest(BaseModel):
    # A length cap keeps prompts (and model cost) bounded.
    question: str = Field(min_length=3, max_length=500)


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html", headers=PAGE_HEADERS)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/ask")
def ask(req: AskRequest):
    return agent.ask(req.question)
