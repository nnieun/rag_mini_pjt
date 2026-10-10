from langchain_openai import ChatOpenAI
from langchain_openai import OpenAIEmbeddings

from common.config import (
    API_KEY,
    BASE_URL,
    EMBEDDING_MODEL,
    MODEL,
    TEMPERATURE,
    MAX_TOKENS
)

def get_llm_model(
    model: str = MODEL,
    api_key: str | None = API_KEY,
    temperature: float = 0,
    max_tokens: int = 512
):
    if not api_key:
        raise ValueError("Set LLM_API_KEY or OPENAI_API_KEY in the .env file.")

    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=BASE_URL,
        temperature=temperature,
        use_responses_api=False,  # base url로 할 때는 이부분 넣어야 함.(MonoRouter 사용)
        max_tokens=max_tokens,
    )


def get_embedding_model():
    if not API_KEY:
        raise ValueError("Set LLM_API_KEY or OPENAI_API_KEY in the .env file.")

    embedding_model = EMBEDDING_MODEL
    embeddings = OpenAIEmbeddings(
        api_key=API_KEY,
        base_url=BASE_URL,
        model=embedding_model
        )
    # print(embeddings)
    return embeddings