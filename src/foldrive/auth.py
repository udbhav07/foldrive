import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/drive"]
APP_DIR = Path(os.environ["APPDATA"])/ "foldrive"
TOKEN_PATH = APP_DIR / "token.json"
CLIENT_SECRET_PATH = APP_DIR / "client_secret.json"


def _save(creds):
    APP_DIR.mkdir(exist_ok=True)
    TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")



def get_credentials():
    if not TOKEN_PATH.exists():
        return None
    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH),SCOPES)
    if creds.valid:
        return creds
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _save(creds)
        return creds
    return None

def login():
    creds=get_credentials()
    if creds:
        return creds
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_PATH), SCOPES)
    creds = flow.run_local_server(port=0)
    _save(creds)
    return creds


        
