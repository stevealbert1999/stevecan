"""Entrena pesos (LoRA) EN CPU sobre un modelo pequeño con el dataset real del sistema y lo convierte a GGUF.
El GGUF resultante sirve (1) como modelo borrador para decodificación especulativa del 30B (acelera 1.5-3x)
y (2) como modelo especializado ligero. Entrenar el 30B en CPU no es viable; por eso se entrena un modelo pequeño.
  python -m stevecan.train run  [--steps N] [--dataset ruta.jsonl]
  python -m stevecan.train check          # comprueba dependencias y rutas sin entrenar
Requiere: pip install -r requirements-train.txt ; LLAMA_CPP_DIR con convert_hf_to_gguf.py y llama-quantize.
"""
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from . import config
from .dataset import build

log = logging.getLogger("train")


def check() -> dict:
    res = {"base_model": config.TRAIN_BASE_MODEL, "llama_cpp_dir": str(config.LLAMA_CPP_DIR or ""), "ok": True}
    for mod in ("torch", "transformers", "peft", "datasets"):
        try:
            __import__(mod); res[mod] = "ok"
        except ImportError:
            res[mod] = "FALTA (pip install -r requirements-train.txt)"; res["ok"] = False
    conv = (config.LLAMA_CPP_DIR / "convert_hf_to_gguf.py") if config.LLAMA_CPP_DIR else None
    res["convert_hf_to_gguf"] = "ok" if conv and conv.exists() else "FALTA (LLAMA_CPP_DIR=/ruta/a/llama.cpp)"
    res["llama-quantize"] = "ok" if shutil.which("llama-quantize") else "FALTA en PATH (opcional)"
    res["threads"] = config.TRAIN_THREADS
    return res


def run(steps: int | None = None, dataset: Path | None = None) -> Path:
    import torch
    from datasets import load_dataset
    from peft import LoraConfig, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer, DataCollatorForLanguageModeling, Trainer, TrainingArguments

    torch.set_num_threads(config.TRAIN_THREADS)
    ds_path = dataset or build()
    n = sum(1 for _ in open(ds_path, encoding="utf-8"))
    if n < config.TRAIN_MIN_EXAMPLES:
        raise SystemExit(f"dataset con {n} ejemplos < TRAIN_MIN_EXAMPLES={config.TRAIN_MIN_EXAMPLES}: los agentes aún no han producido suficiente material")
    ts = time.strftime("%Y%m%d-%H%M%S")
    out_dir = config.MODELS_DIR / f"lora-{ts}"
    tok = AutoTokenizer.from_pretrained(config.TRAIN_BASE_MODEL)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    model = AutoModelForCausalLM.from_pretrained(config.TRAIN_BASE_MODEL, torch_dtype=torch.float32)
    model = get_peft_model(model, LoraConfig(r=config.TRAIN_LORA_R, lora_alpha=2 * config.TRAIN_LORA_R, lora_dropout=0.05,
                                             target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
                                             task_type="CAUSAL_LM"))
    model.print_trainable_parameters()
    raw = load_dataset("json", data_files=str(ds_path), split="train")

    def fmt(ex):
        text = tok.apply_chat_template(ex["messages"], tokenize=False)
        enc = tok(text, truncation=True, max_length=config.TRAIN_MAX_LEN)
        return enc

    tokenized = raw.map(fmt, remove_columns=raw.column_names)
    steps = steps or config.TRAIN_STEPS
    args = TrainingArguments(output_dir=str(out_dir), per_device_train_batch_size=1, gradient_accumulation_steps=8,
                             max_steps=steps, learning_rate=2e-4, logging_steps=5, save_steps=max(steps // 2, 10),
                             save_total_limit=2, report_to=[], use_cpu=True, bf16=False, fp16=False,
                             dataloader_num_workers=0, warmup_steps=min(20, steps // 10 + 1))
    trainer = Trainer(model=model, args=args, train_dataset=tokenized,
                      data_collator=DataCollatorForLanguageModeling(tok, mlm=False))
    t0 = time.time()
    trainer.train()
    log.info("entrenamiento: %d pasos en %.0f min", steps, (time.time() - t0) / 60)
    merged_dir = config.MODELS_DIR / f"merged-{ts}"
    merged = model.merge_and_unload()
    merged.save_pretrained(merged_dir, safe_serialization=True)
    tok.save_pretrained(merged_dir)
    gguf = config.MODELS_DIR / f"stevecan-{ts}-f16.gguf"
    conv = config.LLAMA_CPP_DIR / "convert_hf_to_gguf.py" if config.LLAMA_CPP_DIR else None
    if conv and conv.exists():
        subprocess.run([sys.executable, str(conv), str(merged_dir), "--outfile", str(gguf), "--outtype", "f16"], check=True)
        if shutil.which("llama-quantize"):
            q = config.MODELS_DIR / f"stevecan-{ts}-Q8_0.gguf"
            subprocess.run(["llama-quantize", str(gguf), str(q), "Q8_0"], check=True)
            gguf = q
        log.info("GGUF listo: %s  -> DRAFT_GGUF=%s en .env y reinicia llama-server", gguf, gguf)
    else:
        log.warning("sin convert_hf_to_gguf.py: modelo fusionado en %s (convierte a GGUF con llama.cpp)", merged_dir)
        gguf = merged_dir
    (config.MODELS_DIR / "latest.json").write_text(json.dumps(
        {"model": str(gguf), "dataset": str(ds_path), "examples": n, "steps": steps, "base": config.TRAIN_BASE_MODEL, "ts": ts}, indent=2))
    return gguf


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
    a = sys.argv[1:]
    if a and a[0] == "check":
        print(json.dumps(check(), indent=2, ensure_ascii=False))
    elif a and a[0] == "run":
        steps = int(a[a.index("--steps") + 1]) if "--steps" in a else None
        ds = Path(a[a.index("--dataset") + 1]) if "--dataset" in a else None
        print(run(steps, ds))
    else:
        sys.exit(__doc__)
