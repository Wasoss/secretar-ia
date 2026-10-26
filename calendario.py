import os
import json
import datetime
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import base_datos

SCOPES = ['https://www.googleapis.com/auth/calendar']

def obtener_credenciales_google():
    creds = None
    token_json_str = base_datos.obtener_token()
    
    if token_json_str:
        creds = Credentials.from_authorized_user_info(json.loads(token_json_str), SCOPES)
        
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # Solo se ejecuta en tu PC la primera vez para inyectar el token en Neon
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
            
        base_datos.guardar_token(creds.to_json())
        
    return creds

def obtener_eventos_calendario() -> list:
    try:
        creds = obtener_credenciales_google()
        service = build('calendar', 'v3', credentials=creds)
        ahora = datetime.datetime.utcnow().isoformat() + 'Z'
        eventos_resultado = service.events().list(
            calendarId='primary', timeMin=ahora, maxResults=5, 
            singleEvents=True, orderBy='startTime'
        ).execute()
        return eventos_resultado.get('items', [])
    except Exception as e:
        print(f"Error leyendo Calendar: {e}")
        return []
    
    'reminders': {
    'useDefault': False,
    'overrides': [
        {'method': 'popup', 'minutes': 24 * 60}, # 1 día antes
        {'method': 'popup', 'minutes': 60},      # 1 hora antes
    ],
}

def crear_evento_calendario(resumen: str, fecha_hora: str) -> bool:
    try:
        creds = obtener_credenciales_google()
        service = build('calendar', 'v3', credentials=creds)
        inicio = datetime.datetime.strptime(fecha_hora, "%Y-%m-%d %H:%M")
        fin = inicio + datetime.timedelta(hours=1)
        
        evento = {
            'summary': resumen,
            'start': {'dateTime': inicio.isoformat(), 'timeZone': 'America/Argentina/Buenos_Aires'},
            'end': {'dateTime': fin.isoformat(), 'timeZone': 'America/Argentina/Buenos_Aires'},
        }
        service.events().insert(calendarId='primary', body=evento).execute()
        return True
    except Exception as e:
        print(f"Error creando evento: {e}")
        return False