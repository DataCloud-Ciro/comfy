"""
comfy_generate.py
-----------------
Uso rápido:

    from comfy_generate import generar

    ruta_img = generar(
        workflow_path="image_flux.json",
        prompt_text="Tu prompt aquí",
        comfy_host="http://192.168.31.33:8288",
        out_dir="./outputs"
    )
    print("Imagen descargada en:", ruta_img)
"""

from __future__ import annotations
import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Tuple

import requests


def _post_prompt(workflow: Dict[str, Any], host: str) -> str:
    url = f"{host.rstrip('/')}/prompt"
    # Detectar si workflow ya tiene 'prompt' como clave raíz
    if "prompt" in workflow and len(workflow) == 1:
        payload = workflow  # ya está envuelto
    else:
        payload = {"prompt": workflow}
    print("Payload enviado al servidor:", json.dumps(payload)[:500])  # para debug

    r = requests.post(url, json=payload, timeout=30)
    r.raise_for_status()
    data = r.json()
    return data["prompt_id"]


def _wait_until_done(prompt_id: str, host: str, poll: float, timeout: int) -> Dict[str, Any]:
    url = f"{host.rstrip('/')}/history/{prompt_id}"
    t0 = time.time()
    while True:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        hist = r.json()

        # Esperar si la respuesta está vacía o no contiene el prompt_id
        if not hist or prompt_id not in hist:
            if time.time() - t0 > timeout:
                raise TimeoutError(f"El prompt_id '{prompt_id}' no apareció en {timeout}s")
            time.sleep(poll)
            continue

        data = hist[prompt_id]
        if not data.get("status", {}).get("completed", False):
            if time.time() - t0 > timeout:
                raise TimeoutError(f"Prompt {prompt_id} no terminó en {timeout}s")
            time.sleep(poll)
        else:
            return data


def _pick_last_image(hist: Dict[str, Any]) -> Tuple[str, str]:
    if "outputs" not in hist:
        raise ValueError(f"No se encontraron outputs. Respuesta:\n{json.dumps(hist, indent=2)}")

    outputs = hist["outputs"]
    if not outputs:
        raise ValueError("No se encontraron imágenes en los outputs")

    last_node = sorted(outputs.keys(), key=int)[-1]
    images: List[Dict[str, str]] = outputs[last_node]["images"]
    if not images:
        raise ValueError("El nodo final no contiene imágenes")

    last_image = images[-1]
    return last_image["filename"], last_image.get("subfolder", "")


def _download_image(
    filename: str, subfolder: str, host: str, save_dir: Path
) -> Path:
    """Descarga la imagen y la guarda en save_dir."""
    url = (
        f"{host.rstrip('/')}/view?"
        f"filename={filename}&type=output&subfolder={subfolder}"
    )
    r = requests.get(url, stream=True, timeout=120)
    r.raise_for_status()
    save_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(filename).suffix or ".png"
    local_path = save_dir / f"{uuid.uuid4().hex}{ext}"
    with local_path.open("wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)
    return local_path


def generar(
    workflow_path: str,
    prompt_text: str, 
    comfy_host: str = "http://localhost:8188",
    out_dir: str | Path = "./outputs",
    poll_interval: float = 2,
    timeout: int = 300,
) -> Path:
    """
    Envía el workflow con el prompt indicado y descarga la última imagen.
    """
    # 1) Cargar el workflow
    raw = Path(workflow_path).read_text(encoding="utf-8")
    workflow = json.loads(raw)

    # 2) Sobrescribir el texto del nodo 6 (ajusta si tu ID cambia)
    nodo_6 = workflow["6"]                      # levanta KeyError si no existe
    nodo_6["inputs"]["text"] = prompt_text

    # 3) Empaquetar como {"prompt": workflow} (requisito de la API)
    prompt_wrapper = {"prompt": workflow}

    # 4) Postear prompt y esperar resultado
    prompt_id = _post_prompt(prompt_wrapper, comfy_host)
    print(f"Prompt ID: {prompt_id}")

    hist = _wait_until_done(prompt_id, comfy_host, poll_interval, timeout)
    filename, subfolder = _pick_last_image(hist)
    print(f"Imagen remota: {filename} (subfolder='{subfolder}')")

    local_path = _download_image(filename, subfolder, comfy_host, Path(out_dir))
    return local_path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Genera imagen en ComfyUI y la descarga")
    parser.add_argument("workflow", help="Archivo JSON del workflow (ej. flux.json)")
    parser.add_argument("--prompt", required=True,
                        help='Texto para el nodo 6 (ej. "Messi en la Luna")')
    parser.add_argument("--host", default="http://localhost:8188", help="URL de ComfyUI")
    parser.add_argument("--out", default="./outputs", help="Directorio de salida")
    args = parser.parse_args()

    path = generar(
        args.workflow,
        prompt_text=args.prompt,
        comfy_host=args.host,
        out_dir=args.out,
    )
    print("Imagen guardada en:", path)
