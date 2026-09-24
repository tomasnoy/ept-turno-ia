"""Prueba el agente de interpretacion contra el modelo configurado en .env.

Uso: .venv/Scripts/python -m scripts.probar_interprete "quiero un corte el viernes a la tarde"
"""

import sys
from datetime import date

from app import db, seed
from app.agents.interpreter import interpret, load_catalog
from app.llm.factory import get_provider

conn = db.connect(":memory:")
db.init_db(conn)
business = seed.seed_demo(conn)
business_id = business["id"] if business else 1

mensaje = " ".join(sys.argv[1:]) or "Hola, quiero un corte con Laura el viernes a la tarde"
print(interpret(mensaje, load_catalog(conn, business_id), date.today(), get_provider()))
