import asyncio
import logging
import time
from . import config, memory


class Agent:
    """Bucle infinito: step() -> pausa -> step(). Nunca muere: los errores se registran y se reintenta."""
    name = "agent"
    interval = config.CYCLE_SECONDS

    def __init__(self):
        self.log = logging.getLogger(self.name)

    def skills(self, query: str, n: int = 2, chars: int = 1200) -> str:
        """Skills de la biblioteca (GitHub) aplicables a la tarea; disponible para TODOS los agentes."""
        rows = memory.search_skills(query, n)
        if not rows:
            return ""
        return "\n\nSkills aplicables (síguelos si encajan):\n" + "\n\n".join(
            f"### {r['name']} ({r['source']})\n{r['content'][:chars]}" for r in rows)

    async def step(self) -> str | None:
        raise NotImplementedError

    async def run_forever(self):
        self.log.info("iniciado")
        while True:
            t0 = time.time()
            try:
                msg = await self.step()
                if msg:
                    self.log.info(msg)
                    memory.log_event(self.name, "step", msg)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                self.log.exception("error en step: %s", e)
                memory.log_event(self.name, "error", repr(e))
                await asyncio.sleep(min(60, self.interval * 2))
            elapsed = time.time() - t0
            await asyncio.sleep(max(1.0, self.interval - elapsed))
