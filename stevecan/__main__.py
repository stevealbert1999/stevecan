import argparse
import sys
from .runner import run

p = argparse.ArgumentParser(prog="stevecan", description="8 agentes de aprendizaje sobre el modelo local")
p.add_argument("--minutes", type=float, default=None,
               help="detener ordenadamente tras N minutos (para GitHub Actions); sin valor = 24/7")
p.add_argument("--wait-minutes", type=float, default=None,
               help="minutos máximos esperando al modelo; sin valor = esperar indefinidamente")
a = p.parse_args()
sys.exit(run(a.minutes, a.wait_minutes))
