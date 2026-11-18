"""Permite que las pruebas importen el paquete `app` de backend/."""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Las pruebas de la API y del navegador revisan confirmar/descartar con coincidencias insertadas
# a mano: ahí el motor de IA se apaga. test_motor.py lo enciende para probarlo de verdad.
os.environ.setdefault("IA_ENABLED", "false")
