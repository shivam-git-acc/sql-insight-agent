from fastapi import FastAPI
from pydantic import BaseModel, Field

from app import agent

app = FastAPI(title="SQL Insight Agent")


class AskRequest(BaseModel):
    # A length cap keeps prompts (and model cost) bounded.
    question: str = Field(min_length=3, max_length=500)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/ask")
def ask(req: AskRequest):
    return agent.ask(req.question)
