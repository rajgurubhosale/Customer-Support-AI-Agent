
from langchain_groq import ChatGroq
import os
from dotenv import load_dotenv
load_dotenv()
from langchain_openai import ChatOpenAI

model_name  = os.getenv('MODEL_NAME')
MESHAPI_DEEPSEEK_API = os.getenv("MESHAPI_DEEPSEEK_API")
BASE_URL = os.getenv("BASE_URL")


model = ChatOpenAI(
    model=model_name,
    api_key=MESHAPI_DEEPSEEK_API,
    base_url=BASE_URL,
    temperature=0,
)



# api_key = os.getenv("CHAT_GROQ")     
#model = ChatGroq(
#    model="openai/gpt-oss-120b",
#    api_key=api_key,
#    temperature=0,
#    max_tokens=600,
#)

