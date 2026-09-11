import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI


load_dotenv()

model_name = os.getenv("MODEL_NAME")
MESHAPI_DEEPSEEK_API = os.getenv("MESHAPI_DEEPSEEK_API")
BASE_URL = os.getenv("BASE_URL")


model = ChatOpenAI(
    model=model_name,
    api_key=MESHAPI_DEEPSEEK_API,
    base_url=BASE_URL,
    temperature=0,
)

