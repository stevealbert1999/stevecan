import asyncio
import logging
import signal
import time
from logging.handlers import RotatingFileHandler
from . import config, llm, memory
from .roles import build_agents

EXIT_OK = 0
EXIT_MODEL_UNAVAILABLE = 3


def setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    sh = logging.StreamHandler(); sh.setFormatter(fmt); root.addHandler(sh)
    fh = RotatingFileHandler(config.LOG_PATH, maxBytes=20_000_000, backupCount=5)
    fh.setFormatter(fmt); root.addHandler(fh)
    logging.getLogger("httpx").setLevel(logging.WARNING)


async def wait_for_model(wait_minutes: float | None) -> bool:
    log = logging.getLogger("runner")
    deadline = time.time() + wait_minutes * 60 if wait_minutes else None
    while not await llm.healthy():
        if deadline and time.time() >= deadline:
            log.error("modelo no disponible en %s tras %.0f min", config.LLM_BASE_URL, wait_minutes)
            return False
        log.warning("modelo no disponible en %s; esperando…", config.LLM_BASE_URL)
        await asyncio.sleep(10)
    log.info("modelo disponible: %s", config.LLM_MODEL)
    return True


async def main(minutes: float | None = None, wait_minutes: float | None = None) -> int:
    setup_logging()
    log = logging.getLogger("runner")
    if not await wait_for_model(wait_minutes):
        return EXIT_MODEL_UNAVAILABLE
    requeued = memory.requeue_stale(0)
    if requeued:
        log.info("%d tareas 'running' de una ejecución anterior reencoladas", requeued)
    agents = build_agents()
    log.info("lanzando %d agentes (límite: %s)", len(agents), f"{minutes:g} min" if minutes else "sin límite, 24/7")
    tasks = [asyncio.create_task(a.run_forever(), name=a.name) for a in agents]
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            pass
    try:
        await asyncio.wait_for(stop.wait(), timeout=minutes * 60 if minutes else None)
        log.info("señal de parada recibida")
    except asyncio.TimeoutError:
        log.info("límite de %g min alcanzado; parada ordenada", minutes)
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    log.info("agentes detenidos; estado: %s", memory.stats())
    return EXIT_OK


def run(minutes: float | None = None, wait_minutes: float | None = None) -> int:
    try:
        return asyncio.run(main(minutes, wait_minutes))
    except KeyboardInterrupt:
        return EXIT_OK
