import os

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI


# Explicitly load keys from the .env file.
load_dotenv()


def get_llm_client():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("CRITICAL: GEMINI_API_KEY is missing from your .env file.")

    # Default to Flash for local smoke tests; set GEMINI_MODEL=gemini-2.5-pro
    # in .env when you need stronger text-to-SQL reasoning.
    llm = ChatGoogleGenerativeAI(
        model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        google_api_key=api_key,
        temperature=0.0,
    )
    return llm
