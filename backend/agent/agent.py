import os

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    raise RuntimeError("GEMINI_API_KEY не найден в .env")

HISTORY_LIMIT = 20
history: dict[str, list[types.Content]] = {}

client = genai.Client(api_key=api_key)
MODEL = "gemini-3.5-flash-lite"


def handle_message(user_id: str, text: str, session_id: str | None = None) -> str:
    key = session_id or user_id
    past = history.get(key, [])
    user_msg = types.Content(role="user", parts=[types.Part(text=text)])

    response =  client.models.generate_content(
        model=MODEL,
        contents=[*past, user_msg]
    )

    reply = response.text
    if reply:
        model_msg = types.Content(role="model", parts=[types.Part(text=reply)])
        history[key] = [*past, user_msg, model_msg][-HISTORY_LIMIT:]
    return reply


if __name__ == "__main__":
    print(handle_message("u1", "Меня зовут Артём, я люблю бегать"))
    print(handle_message("u1", "Как меня зовут и что я люблю?"))
    print(handle_message("u2", "Как меня зовут?"))