import os

from dotenv import load_dotenv

load_dotenv()

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")

DB_PATH = os.getenv("DB_PATH", "data/turnos.db")

TIMEZONE = os.getenv("TIMEZONE", "America/Argentina/Buenos_Aires")
BUSINESS_NAME = os.getenv("BUSINESS_NAME", "Peluquería Demo")

# Clave del panel del negocio. Si esta vacia, el panel queda deshabilitado.
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")
