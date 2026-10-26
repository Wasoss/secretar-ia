import os
from groq import Groq
from dotenv import load_dotenv

load_dotenv()
cliente = Groq(api_key=os.getenv("GROQ_API_KEY"))
for modelo in cliente.models.list().data:
    print(modelo.id)