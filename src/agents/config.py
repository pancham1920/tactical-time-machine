import os

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI


# Local development may use .env. Hosted environment variables take precedence.
load_dotenv(override=False)


def get_llm_client():
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key or api_key == "replace_with_your_gemini_api_key":
        raise ValueError(
            "GEMINI_API_KEY is required. Set it in the backend environment "
            "or a local .env file; do not use the example placeholder."
        )

    # Default to Flash for local smoke tests; set GEMINI_MODEL=gemini-2.5-pro
    # in .env when you need stronger text-to-SQL reasoning.
    llm = ChatGoogleGenerativeAI(
        model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        google_api_key=api_key,
        temperature=0.0,
        max_retries=0,
        max_output_tokens=2048,
        timeout=30,
    )
    return llm
