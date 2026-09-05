
from langchain_groq import ChatGroq
import os
from dotenv import load_dotenv
load_dotenv()
api_key = os.getenv("CHAT_GROQ")     

model = ChatGroq(
    model = "openai/gpt-oss-120b",
    api_key=api_key,
    temperature=0
)