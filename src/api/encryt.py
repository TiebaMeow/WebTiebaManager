from hashlib import md5

from src.core.controller import Controller


def encrypt(password: str):
    if Controller.config.server.encryption_method == "plain":
        return password
    elif Controller.config.server.encryption_method == "md5":
        return md5(f"{password}.{Controller.config.server.encryption_salt}".encode()).hexdigest()
    raise ValueError(f"unknown encryption type {Controller.config.server.encryption_method}")
