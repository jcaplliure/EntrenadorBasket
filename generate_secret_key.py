#!/usr/bin/env python3
"""
Script para generar una SECRET_KEY segura para Flask
Ejecutar: python3 generate_secret_key.py
"""
import secrets

if __name__ == '__main__':
    secret_key = secrets.token_hex(32)
    print(f"\nSECRET_KEY generada:")
    print(f"{secret_key}\n")
    print("Copia esta clave y añádela a tu archivo .env:")
    print(f"SECRET_KEY={secret_key}\n")
