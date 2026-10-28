
import asyncio
from google_auth_oauthlib.flow import InstalledAppFlow
from config.settings import settings
from infrastructure.database.connection import init_db, get_pool
from infrastructure.database.repositories.credential_repo import CredentialRepository

SCOPES = ['https://www.googleapis.com/auth/calendar']

async def main():
    await init_db()
    flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
    creds = flow.run_local_server(port=8080)
    pool = await get_pool()
    await CredentialRepository(pool).save_token("google_calendar", creds.to_json())
    print("✅ Token NUEVO con scope completo guardado en Neon")

asyncio.run(main())
# → Se abre navegador → Elegí tu cuenta → Permitir → Listo