import sys
from pathlib import Path

from dotenv import load_dotenv
from garminconnect import Garmin
import os

BASE_DIR = Path(__file__).parent


def token_store(persona=None):
    base = BASE_DIR / "data"
    return base / ".tokens" if not persona else base / persona / ".tokens"


def get_client(persona=None):
    """Devuelve un cliente Garmin autenticado.

    Perfil por defecto: .env y data/.tokens. Otra persona (--persona ana):
    .env.ana y data/ana/.tokens, para tener varias cuentas de Garmin separadas.

    client.login(tokenstore) reutiliza el token guardado (sin contrasena); si no
    existe o ha caducado, hace login con GARMIN_EMAIL/GARMIN_PASSWORD del .env
    correspondiente y guarda el token nuevo para la proxima vez.
    """
    env_file = BASE_DIR / (".env" if not persona else f".env.{persona}")
    load_dotenv(env_file, override=True)

    email = os.getenv("GARMIN_EMAIL")
    password = os.getenv("GARMIN_PASSWORD")

    store = token_store(persona)
    store.parent.mkdir(parents=True, exist_ok=True)
    client = Garmin(
        email=email,
        password=password,
        prompt_mfa=lambda: input("Codigo de verificacion (MFA) de Garmin: "),
    )
    try:
        client.login(str(store))
    except Exception as e:
        print(
            f"No se pudo iniciar sesion. Revisa GARMIN_EMAIL/GARMIN_PASSWORD en {env_file.name} "
            f"(copia .env.example a {env_file.name} si no lo has hecho). Detalle: {e}",
            file=sys.stderr,
        )
        sys.exit(1)

    return client
