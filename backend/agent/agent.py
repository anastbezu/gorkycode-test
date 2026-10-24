import os
from dotenv import load_dotenv
from google import genai

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    raise RuntimeError("GEMINI_API_KEY не найден в .env")


client = genai.Client(api_key=api_key)
MODEL = "gemini-3.5-flash-lite"


def handle_message(user_id: str, text: str) -> str:
    response =  client.models.generate_content(
        model=MODEL,
        contents=text
    )
    return response.text


if __name__ == "__main__":
    print(handle_message("test", "Привет, что ты умеешь?"))