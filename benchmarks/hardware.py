"""Coleta local somente de leitura; ausência de sensor não vira uso zero."""

import csv
import io
import math
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import time

try:
    import psutil
except ImportError:
    psutil = None


def numero(valor):
    try:
        valor = float(valor)
        return valor if math.isfinite(valor) and valor >= 0 else None
    except (ValueError, TypeError):
        return None


def localizar_nvidia_smi():
    encontrado = shutil.which("nvidia-smi")
    if encontrado:
        return encontrado
    if os.name != "nt":
        return None
    windows = Path(os.environ.get("WINDIR", "C:/Windows"))
    candidatos = [windows / "System32/nvidia-smi.exe",
                  Path(os.environ.get("ProgramFiles", "C:/Program Files")) /
                  "NVIDIA Corporation/NVSMI/nvidia-smi.exe"]
    try:
        candidatos.extend(sorted((windows / "System32/DriverStore/FileRepository").glob(
            "nv*/nvidia-smi.exe"), key=lambda path: path.stat().st_mtime, reverse=True))
        return next((str(path) for path in candidatos if path.is_file()), None)
    except OSError:
        return None


def ler_gpus(csv_texto):
    gpus = []
    for campos in csv.reader(io.StringIO(csv_texto), skipinitialspace=True):
        if len(campos) != 7 or numero(campos[0]) is None:
            continue
        usados, total = numero(campos[3]), numero(campos[4])
        gpus.append({
            "indice": int(float(campos[0])), "nome": campos[1].strip(),
            "uso_percent": numero(campos[2]), "vram_usada_mb": usados,
            "vram_total_mb": total,
            "vram_percent": usados / total * 100 if usados is not None and total else None,
            "temperatura_c": numero(campos[5]), "potencia_w": numero(campos[6]),
        })
    return gpus


class ColetorHardware:
    def __init__(self, ferramenta=None, sistema=None, executar=subprocess.run):
        self.ferramenta = localizar_nvidia_smi() if ferramenta is None else ferramenta
        self.sistema = psutil if sistema is None else sistema
        self.executar = executar
        self._cpu_iniciada = False

    def coletar(self):
        amostra = {
            "instante": time.time(), "cpu_percent": None, "ram_percent": None,
            "ram_usada_mb": None, "ram_total_mb": None, "processo_ram_mb": None,
            "cpu_status": "psutil indisponível", "gpus": [],
            "gpu_status": "NVIDIA não detectada",
        }
        if self.sistema is not None:
            try:
                cpu = numero(self.sistema.cpu_percent(interval=None))
                amostra["cpu_percent"] = cpu if self._cpu_iniciada else None
                self._cpu_iniciada = True
                memoria = self.sistema.virtual_memory()
                amostra.update(
                    ram_percent=numero(memoria.percent),
                    ram_usada_mb=(memoria.total - memoria.available) / 1024 ** 2,
                    ram_total_mb=memoria.total / 1024 ** 2,
                    processo_ram_mb=self.sistema.Process().memory_info().rss / 1024 ** 2,
                    cpu_status="disponível",
                )
            except (OSError, RuntimeError, AttributeError):
                amostra["cpu_status"] = "sensor do sistema indisponível"
        if self.ferramenta:
            try:
                retorno = self.executar([
                    self.ferramenta,
                    "--query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
                    "--format=csv,noheader,nounits",
                ], capture_output=True, text=True, timeout=2, check=False,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                if retorno.returncode == 0:
                    amostra["gpus"] = ler_gpus(retorno.stdout)
                amostra["gpu_status"] = "disponível" if amostra["gpus"] else "sensor NVIDIA indisponível"
            except (OSError, subprocess.TimeoutExpired):
                amostra["gpu_status"] = "sensor NVIDIA indisponível"
        return amostra


def resumir_hardware(amostras):
    def resumo(valores):
        validos = [v for v in valores if v is not None]
        return {"media": statistics.mean(validos), "pico": max(validos), "n": len(validos)} if validos else None

    resultado = {
        "amostras": len(amostras),
        "cpu_percent": resumo([a["cpu_percent"] for a in amostras]),
        "ram_percent": resumo([a["ram_percent"] for a in amostras]),
        "ram_usada_mb": resumo([a["ram_usada_mb"] for a in amostras]),
        "gpus": [],
    }
    indices = sorted({g["indice"] for a in amostras for g in a["gpus"]})
    for indice in indices:
        leituras = [g for a in amostras for g in a["gpus"] if g["indice"] == indice]
        resultado["gpus"].append({
            "indice": indice, "nome": leituras[-1]["nome"],
            **{campo: resumo([g[campo] for g in leituras]) for campo in (
                "uso_percent", "vram_usada_mb", "vram_percent", "temperatura_c", "potencia_w")},
        })
    return resultado
