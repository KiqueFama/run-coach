"""Cifrado de los datos: AES-256-GCM con clave derivada por PBKDF2-SHA256.

El mismo formato lo descifra la app en el navegador (WebCrypto), asi que no cambies
nada aqui sin cambiar tambien la app. La clave se normaliza (sin espacios, en minusculas)
para que sea facil escribirla en el movil.
"""
import base64
import json
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ITERACIONES = 600_000


def _normalizar(clave: str) -> bytes:
    return clave.strip().lower().encode("utf-8")


def _derivar(clave: str, sal: bytes, iteraciones: int) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=sal, iterations=iteraciones)
    return kdf.derive(_normalizar(clave))


def cifrar(texto: str, clave: str) -> str:
    sal = os.urandom(16)
    iv = os.urandom(12)
    ct = AESGCM(_derivar(clave, sal, ITERACIONES)).encrypt(iv, texto.encode("utf-8"), None)
    return json.dumps(
        {
            "v": 1,
            "kdf": "PBKDF2-SHA256",
            "iter": ITERACIONES,
            "salt": base64.b64encode(sal).decode(),
            "iv": base64.b64encode(iv).decode(),
            "ct": base64.b64encode(ct).decode(),
        }
    )


def descifrar(contenido: str, clave: str) -> str:
    o = json.loads(contenido)
    sal = base64.b64decode(o["salt"])
    iv = base64.b64decode(o["iv"])
    ct = base64.b64decode(o["ct"])
    return AESGCM(_derivar(clave, sal, int(o["iter"]))).decrypt(iv, ct, None).decode("utf-8")
