import json
import re

from app import db, llm

SQL_SYSTEM = """You write PostgreSQL queries for a business analyst.
Given a schema and a question, reply with exactly one SELECT statement
inside a ```sql code block and nothing else. Use only tables and columns
from the schema."""

ANSWER_SYSTEM = """You explain query results to a non-technical business user.
Answer the question in 1-3 sentences using only the rows provided.
If the rows are empty, say no data was found."""


def extract_sql(text: str) -> str:
    match = re.search(r"```sql\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    return (match.group(1) if match else text).strip().rstrip(";")


def ask(question: str, max_attempts: int = 2) -> dict:
    schema = db.get_schema()
    prompt = f"Schema:\n{schema}\n\nQuestion: {question}"
    sql, error = "", None

    for _ in range(max_attempts):
        sql = extract_sql(llm.chat(SQL_SYSTEM, prompt))
        try:
            columns, rows = db.run_query(sql)
            error = None
            break
        except Exception as exc:  # feed the DB error back to the model once
            error = str(exc)
            prompt += f"\n\nYour previous query failed:\n{sql}\nError: {error}\nFix it."

    if error:
        return {"question": question, "sql": sql, "error": error}

    preview = json.dumps([dict(zip(columns, r)) for r in rows[:50]], default=str)
    answer = llm.chat(ANSWER_SYSTEM, f"Question: {question}\nRows: {preview}")
    return {
        "question": question,
        "sql": sql,
        "columns": columns,
        "rows": [[str(v) if v is not None else None for v in r] for r in rows],
        "answer": answer,
    }
