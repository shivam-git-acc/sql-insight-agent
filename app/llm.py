import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# Azure OpenAI v1 endpoint. If the "Continue in code" snippet in Foundry
# shows a different client setup, use that one instead.
client = OpenAI(
    base_url=os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/") + "/openai/v1/",
    api_key=os.environ["AZURE_OPENAI_API_KEY"],
)
MODEL = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-5-mini")


def chat(system: str, user: str) -> str:
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return resp.choices[0].message.content or ""
