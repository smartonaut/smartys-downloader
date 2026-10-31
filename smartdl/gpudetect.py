"""GPU-Erkennung + Modell-Empfehlung: liest die Grafikkarte aus und schlägt vor,
welche KI-Modelle auf dem System laufen (nach VRAM).

Windows/Linux: nvidia-smi für NVIDIA (VRAM), lspci als Fallback (AMD/Intel).
Ohne GPU → CPU-only, nur kleine Modelle.
"""
import subprocess

# Empfehlung: (min VRAM in GB, Modell, Beschreibung) — Q4-Quantisierung ≈ VRAM
RECOMMENDED = [
    (1.0, "qwen2.5:1.5b", "Qwen2.5 1.5B — sehr klein, läuft auch auf CPU"),
    (2.5, "qwen2.5:3b", "Qwen2.5 3B — klein, ab 4 GB VRAM"),
    (6.0, "qwen2.5:7b", "Qwen2.5 7B — empfohlen, ab 8 GB VRAM"),
    (11.0, "qwen2.5:14b", "Qwen2.5 14B — stark, ab 16 GB VRAM"),
    (22.0, "qwen2.5:32b", "Qwen2.5 32B — sehr stark, ab 24 GB VRAM"),
]


def _nvidia_smi() -> dict | None:
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, timeout=10, text=True)
        if r.returncode != 0 or not r.stdout.strip():
            return None
        name, vram_mb = r.stdout.strip().splitlines()[0].split(",", 1)
        return {"vendor": "nvidia", "name": name.strip(),
                "vram_gb": round(int(vram_mb.strip()) / 1024, 1)}
    except Exception:
        return None


def _lspci() -> str:
    try:
        r = subprocess.run(["lspci"], capture_output=True, timeout=10, text=True)
        for line in r.stdout.splitlines():
            low = line.lower()
            if any(k in low for k in ("vga", "3d", "display controller")):
                return line.split(": ", 1)[1] if ": " in line else line.strip()
    except Exception:
        pass
    return ""


def detect_gpu() -> dict:
    gpu = _nvidia_smi()
    if gpu:
        return gpu
    desc = _lspci()
    if desc:
        return {"vendor": "unknown", "name": desc, "vram_gb": 0}
    return {"vendor": "cpu", "name": "keine GPU erkannt", "vram_gb": 0}


def recommend_models(vram_gb: float) -> list[dict]:
    """Passende Modelle für die VRAM-Größe (alle die reinpassen)."""
    if vram_gb <= 0:
        # CPU-only → nur die kleinen
        return [
            {"model": "qwen2.5:1.5b", "desc": "Qwen2.5 1.5B (CPU-tauglich)"},
            {"model": "qwen2.5:3b", "desc": "Qwen2.5 3B (CPU, langsam)"},
        ]
    out = []
    for min_vram, model, desc in RECOMMENDED:
        if min_vram <= vram_gb * 1.2:  # Q4 ≈ size in GB, Puffer 20 %
            out.append({"model": model, "desc": desc})
    return out


def gpu_summary() -> dict:
    gpu = detect_gpu()
    gpu["recommended"] = recommend_models(gpu["vram_gb"])
    return gpu
