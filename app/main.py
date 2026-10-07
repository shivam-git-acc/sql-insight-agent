from fastapi import FastAPI
from pydantic import BaseModel

from app import agent

app = FastAPI(title="SQL Insight Agent")


class AskRequest(BaseModel):
    question: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/ask")
def ask(req: AskRequest):
    return agent.ask(req.question)
