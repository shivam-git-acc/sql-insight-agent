import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# Azure OpenAI v1 endpoint: AZURE_OPENAI_ENDPOINT must be only the base,
# e.g. https://<resource>.openai.azure.com, with no path after it.
client = OpenAI(
    base_url=os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/") + "/openai/v1/",
    api_key=os.environ["AZURE_OPENAI_API_KEY"],
)
MODEL = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-5-mini")


def chat(system: str, user: str) -> tuple[str, int]:
    """Return (reply text, total tokens used)."""
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    tokens = resp.usage.total_tokens if resp.usage else 0
    return resp.choices[0].message.content or "", tokens
