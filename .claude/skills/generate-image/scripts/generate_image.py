#!/usr/bin/env python3
"""
Unified image generation script — single entry point for all image providers.

Auto-detects provider from IMAGE_API_KEY format:
  - Starts with "nvapi-" → NVIDIA NIM endpoint
  - Otherwise → OpenAI-compatible chat/completions endpoint

Supports both image generation and editing (with input image).

Usage:
    python generate_image.py "A scientific diagram of a neural network" -o output.png
    python generate_image.py "Flowchart" -o flow.png --model agnes-2.0-flash
    python generate_image.py "Add a hat" -o edited.png --input original.png

Environment variables (all IMAGE_* — fully decoupled from writing model):
    IMAGE_API_KEY        API key (required) — auto-detects NVIDIA vs OpenAI
    IMAGE_BASE_URL       Base URL for OpenAI-compatible endpoint
    IMAGE_MODEL          Model name (default: agnes-2.0-flash)
"""

import argparse
import base64
import json
import os
import re
import sys
import time
import random
from pathlib import Path
from typing import Optional, Dict, Any, List

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ── Constants ────────────────────────────────────────────────────────────────
NVIDIA_NIM_BASE_URL = "https://ai.api.nvidia.com/v1/genai"
DEFAULT_OPENAI_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_IMAGE_MODEL = "agnes-2.0-flash"
REQUEST_TIMEOUT = 120
MAX_RETRIES = 3
MAX_PROMPT_LENGTH = 10000
MAX_IMAGE_SIZE_MB = 20

SCIENTIFIC_STYLE_SUFFIX = (
    " Clean white background, sharp lines, high contrast, "
    "publication-ready quality, sans-serif labels, no gradients or shadows, "
    "professional scientific illustration style."
)

# NVIDIA NIM supported models and their parameters
NVIDIA_MODELS = {
    "stabilityai/stable-diffusion-xl": {
        "name": "Stable Diffusion XL",
        "max_width": 1024, "max_height": 1024,
        "default_steps": 25, "default_cfg": 5.0,
        "supports_negative": True,
    },
    "stabilityai/stable-diffusion-3-medium": {
        "name": "Stable Diffusion 3 Medium",
        "max_width": 1024, "max_height": 1024,
        "default_steps": 30, "default_cfg": 7.0,
        "supports_negative": True,
    },
    "stabilityai/sdxl-turbo": {
        "name": "SDXL Turbo",
        "max_width": 1024, "max_height": 1024,
        "default_steps": 4, "default_cfg": 0.0,
        "supports_negative": False,
    },
    "nvidia/consistory": {
        "name": "ConsistoryV2",
        "max_width": 1024, "max_height": 1024,
        "default_steps": 30, "default_cfg": 5.0,
        "supports_negative": True,
    },
    "black-forest-labs/flux.1-dev": {
        "name": "Flux.1 Dev",
        "max_width": 1024, "max_height": 1024,
        "default_steps": 30, "default_cfg": 3.5,
        "supports_negative": True,
    },
    "black-forest-labs/flux.1-schnell": {
        "name": "Flux.1 Schnell",
        "max_width": 1024, "max_height": 1024,
        "default_steps": 4, "default_cfg": 0.0,
        "supports_negative": False,
    },
}

NVIDIA_DEFAULT_MODEL = "black-forest-labs/flux.1-dev"


# ── Env Loading ──────────────────────────────────────────────────────────────
def _load_env():
    """Walk up directories to find and load .env file."""
    current = Path(__file__).resolve().parent
    for _ in range(8):
        env_path = current / ".env"
        if env_path.exists():
            try:
                from dotenv import load_dotenv
                load_dotenv(env_path, override=False)
                return
            except ImportError:
                with open(env_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#') and '=' in line:
                            key, val = line.split('=', 1)
                            key = key.strip()
                            val = val.strip().strip('"').strip("'")
                            if key and key not in os.environ:
                                os.environ[key] = val
                return
        if current == current.parent:
            break
        current = current.parent


_load_env()


# ── Style Directives ─────────────────────────────────────────────────────────
def _load_style_directives() -> str:
    """Load unified style directives from sci_figure_style, with fallback."""
    try:
        here = Path(__file__).resolve().parent
        scripts_dir = here.parent.parent.parent.parent / "scripts"
        style_file = scripts_dir / "sci_figure_style.py"
        if style_file.exists():
            import importlib.util
            spec = importlib.util.spec_from_file_location("sci_figure_style", style_file)
            if spec and spec.loader:
                sfx = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(sfx)
                return sfx.get_ai_style_directives()
    except Exception:
        pass
    return """VISUAL STYLE (mandatory):
- Color palette: Okabe-Ito colorblind-safe
- Font: Arial or Helvetica (sans-serif only)
- Background: solid white, no gradients or textures
- No drop shadows, no 3D effects, no decorative elements
- Clean, minimal, publication-ready aesthetic"""


_UNIFIED_STYLE = _load_style_directives()


# ── Config ───────────────────────────────────────────────────────────────────
def _is_nvidia_key(key: str) -> bool:
    """Detect NVIDIA API key by its nvapi- prefix."""
    return key.startswith("nvapi-")


def get_image_config() -> tuple:
    """Get IMAGE_API_KEY, IMAGE_BASE_URL, IMAGE_MODEL from environment."""
    api_key = os.environ.get("IMAGE_API_KEY") or ""
    if not api_key:
        raise ValueError(
            "[ERROR] IMAGE_API_KEY not found!\n\n"
            "Set in your .env file:\n"
            "  IMAGE_API_KEY=your-api-key\n\n"
            "Provider auto-detection:\n"
            '  - Key starts with "nvapi-" → NVIDIA NIM\n'
            "  - Otherwise → OpenAI-compatible chat/completions endpoint\n"
        )

    if _is_nvidia_key(api_key):
        default_base = ""
    else:
        default_base = os.environ.get("IMAGE_BASE_URL", DEFAULT_OPENAI_BASE_URL).rstrip("/")

    model = os.environ.get("IMAGE_MODEL", DEFAULT_IMAGE_MODEL)
    return api_key, default_base, model


# ── Backend: NVIDIA NIM ──────────────────────────────────────────────────────
def _generate_nvidia(
    prompt: str,
    model: str,
    api_key: str,
    width: int = 1024,
    height: int = 1024,
    steps: Optional[int] = None,
    cfg_scale: Optional[float] = None,
    seed: Optional[int] = None,
    negative_prompt: str = "",
    scientific_mode: bool = True,
) -> bytes:
    """Generate image via NVIDIA NIM API."""
    try:
        import requests
    except ImportError:
        raise RuntimeError("[ERROR] 'requests' library required. Install: pip install requests")

    model_info = NVIDIA_MODELS.get(model)
    if model_info is None:
        raise ValueError(
            f"[ERROR] Unsupported NVIDIA model: {model}\n"
            f"Supported: {', '.join(NVIDIA_MODELS.keys())}"
        )

    width = min(width, model_info["max_width"])
    height = min(height, model_info["max_height"])
    if steps is None:
        steps = model_info["default_steps"]
    if cfg_scale is None:
        cfg_scale = model_info["default_cfg"]

    full_prompt = prompt + SCIENTIFIC_STYLE_SUFFIX if scientific_mode else prompt

    print(f"[NVIDIA NIM] Generating with {model_info['name']} ({model})")
    print(f"  Size: {width}x{height}, Steps: {steps}, CFG: {cfg_scale}")

    url = f"{NVIDIA_NIM_BASE_URL}/{model}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }

    payload: Dict[str, Any] = {
        "text_prompts": [{"text": full_prompt, "weight": 1.0}],
        "cfg_scale": cfg_scale,
        "sampler": "K_DPM_2_ANCESTRAL",
        "seed": seed if seed is not None else random.randint(0, 2**32 - 1),
        "steps": steps,
        "width": width,
        "height": height,
    }

    if negative_prompt and model_info["supports_negative"]:
        payload["text_prompts"].append({"text": negative_prompt, "weight": -1.0})

    last_exception = None
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT)
            if response.status_code == 200:
                break
            elif response.status_code == 402:
                raise RuntimeError(
                    "[ERROR] NVIDIA NIM credits exhausted. "
                    "Get more at https://build.nvidia.com/"
                )
            elif response.status_code in (429, 500, 502, 503, 504):
                delay = 2 ** attempt + random.uniform(0, 1)
                print(f"[WARN] HTTP {response.status_code}. Retrying in {delay:.1f}s...")
                time.sleep(delay)
                last_exception = RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")
            else:
                raise RuntimeError(f"[ERROR] NVIDIA API Error ({response.status_code}): {response.text}")
        except requests.exceptions.Timeout:
            delay = 2 ** attempt + random.uniform(0, 1)
            print(f"[WARN] Timeout. Retrying in {delay:.1f}s...")
            time.sleep(delay)
            last_exception = RuntimeError("[ERROR] Request timed out")
        except requests.exceptions.RequestException as e:
            if "credits exhausted" in str(e):
                raise
            delay = 2 ** attempt + random.uniform(0, 1)
            print(f"[WARN] Request failed: {e}. Retrying in {delay:.1f}s...")
            time.sleep(delay)
            last_exception = RuntimeError(f"[ERROR] Request failed: {e}")
    else:
        raise last_exception  # type: ignore[misc]

    if response.status_code != 200:
        raise RuntimeError(f"[ERROR] NVIDIA API Error ({response.status_code}): {response.text}")

    result = response.json()
    artifacts = result.get("artifacts", [])
    if not artifacts:
        raise RuntimeError(f"[ERROR] No image in NVIDIA response: {json.dumps(result)[:500]}")

    image_b64 = artifacts[0].get("base64")
    if not image_b64:
        raise RuntimeError("[ERROR] No base64 image data in response artifact")

    finish_reason = artifacts[0].get("finishReason", "unknown")
    if finish_reason == "CONTENT_FILTERED":
        raise RuntimeError("[ERROR] Image filtered by NVIDIA safety system. Try a different prompt.")

    return base64.b64decode(image_b64)


# ── Backend: OpenAI-compatible (chat/completions) ────────────────────────────
def _load_image_as_base64(image_path: str) -> str:
    """Load an image file and return as a base64 data URL."""
    path = Path(image_path)
    if not path.exists():
        raise ValueError(f"[ERROR] Image file not found: {image_path}")

    file_size = path.stat().st_size
    max_bytes = MAX_IMAGE_SIZE_MB * 1024 * 1024
    if file_size > max_bytes:
        raise ValueError(
            f"[ERROR] Image too large: {file_size / (1024*1024):.1f} MB "
            f"(max {MAX_IMAGE_SIZE_MB} MB): {image_path}"
        )

    ext = path.suffix.lower()
    mime_types = {
        '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
        '.gif': 'image/gif', '.webp': 'image/webp',
    }
    mime_type = mime_types.get(ext, 'image/png')

    with open(path, 'rb') as f:
        image_data = f.read()
    base64_data = base64.b64encode(image_data).decode('utf-8')
    return f"data:{mime_type};base64,{base64_data}"


def _extract_image_from_chat_response(response: Dict[str, Any]) -> Optional[bytes]:
    """Extract base64 image from chat/completions response."""
    try:
        choices = response.get("choices", [])
        if not choices:
            return None

        message = choices[0].get("message", {})

        # Primary: 'images' field (Nano Banana Pro, agnes, etc.)
        images = message.get("images", [])
        if images and len(images) > 0:
            first_image = images[0]
            if isinstance(first_image, dict):
                if first_image.get("type") == "image_url":
                    url = first_image.get("image_url", {})
                    if isinstance(url, dict):
                        url = url.get("url", "")
                    if url and url.startswith("data:image") and "," in url:
                        b64_str = url.split(",", 1)[1].replace('\n', '').replace('\r', '').replace(' ', '')
                        return base64.b64decode(b64_str)

        # Fallback: content field (string with data:image)
        content = message.get("content", "")
        if isinstance(content, str) and "data:image" in content:
            match = re.search(r'data:image/[^;]+;base64,([A-Za-z0-9+/=\n\r]+)', content, re.DOTALL)
            if match:
                b64_str = match.group(1).replace('\n', '').replace('\r', '').replace(' ', '')
                return base64.b64decode(b64_str)

        # Fallback: content as list of blocks
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "image_url":
                    url = block.get("image_url", {})
                    if isinstance(url, dict):
                        url = url.get("url", "")
                    if url and url.startswith("data:image") and "," in url:
                        b64_str = url.split(",", 1)[1].replace('\n', '').replace('\r', '').replace(' ', '')
                        return base64.b64decode(b64_str)

        return None
    except Exception:
        return None


def _generate_chat_completions(
    prompt: str,
    model: str,
    api_key: str,
    base_url: str,
    input_image: Optional[str] = None,
    scientific_mode: bool = True,
) -> bytes:
    """Generate image via OpenAI-compatible chat/completions endpoint."""
    try:
        import requests
    except ImportError:
        raise RuntimeError("[ERROR] 'requests' library required. Install: pip install requests")

    is_editing = input_image is not None

    styled_prompt = f"""{_UNIFIED_STYLE}

USER REQUEST: {prompt}

Generate a high-quality image that follows the visual style guidelines above."""

    if is_editing:
        print(f"[IMAGE] Editing with model: {model}")
        print(f"  Input: {input_image}")
        image_data_url = _load_image_as_base64(input_image)
        message_content: Any = [
            {"type": "text", "text": styled_prompt},
            {"type": "image_url", "image_url": {"url": image_data_url}},
        ]
    else:
        print(f"[IMAGE] Generating with model: {model}")
        print(f"  Prompt: {prompt[:80]}{'...' if len(prompt) > 80 else ''}")
        message_content = styled_prompt

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/research-assistant",
        "X-Title": "Image Generator",
    }

    payload: Dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": message_content}],
        "modalities": ["image", "text"],
    }

    last_exception = None
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.post(
                f"{base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=REQUEST_TIMEOUT,
            )

            if response.status_code == 200:
                break
            elif response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else 2 ** attempt + random.uniform(0, 1)
                print(f"[WARN] Rate limited. Retrying in {delay:.1f}s...")
                time.sleep(delay)
                last_exception = RuntimeError(f"Rate limited: {response.text[:200]}")
            elif response.status_code >= 500:
                delay = 2 ** attempt + random.uniform(0, 1)
                print(f"[WARN] Server error ({response.status_code}). Retrying in {delay:.1f}s...")
                time.sleep(delay)
                last_exception = RuntimeError(f"Server error: {response.text[:200]}")
            else:
                raise RuntimeError(f"[ERROR] API Error ({response.status_code}): {response.text}")
        except requests.exceptions.Timeout:
            delay = 2 ** attempt + random.uniform(0, 1)
            print(f"[WARN] Timeout. Retrying in {delay:.1f}s...")
            time.sleep(delay)
            last_exception = RuntimeError("[ERROR] Request timed out")
        except requests.exceptions.RequestException as e:
            delay = 2 ** attempt + random.uniform(0, 1)
            print(f"[WARN] Request failed: {e}. Retrying in {delay:.1f}s...")
            time.sleep(delay)
            last_exception = RuntimeError(f"[ERROR] Request failed: {e}")
    else:
        raise last_exception  # type: ignore[misc]

    if response.status_code != 200:
        raise RuntimeError(f"[ERROR] API Error ({response.status_code}): {response.text}")

    result = response.json()

    if "error" in result:
        error_msg = result["error"]
        if isinstance(error_msg, dict):
            error_msg = error_msg.get("message", str(error_msg))
        raise RuntimeError(f"[ERROR] API Error: {error_msg}")

    image_data = _extract_image_from_chat_response(result)
    if not image_data:
        raise RuntimeError(
            "[ERROR] No image data in response. "
            "The model may not support image generation. "
            "Try a different model (e.g., agnes-2.0-flash, google/gemini-3-pro-image-preview)."
        )

    return image_data


# ── Main API ─────────────────────────────────────────────────────────────────
def generate_image(
    prompt: str,
    output_path: str = "generated_image.png",
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    input_image: Optional[str] = None,
    width: int = 1024,
    height: int = 1024,
    steps: Optional[int] = None,
    cfg_scale: Optional[float] = None,
    seed: Optional[int] = None,
    negative_prompt: str = "",
    scientific_mode: bool = True,
) -> Dict[str, Any]:
    """Generate an image, auto-detecting provider from API key format.

    Provider detection:
      - IMAGE_API_KEY starts with "nvapi-" → NVIDIA NIM endpoint
      - Otherwise → OpenAI-compatible chat/completions endpoint

    Args:
        prompt: Text description of the image.
        output_path: Path to save the generated image.
        model: Model ID (default from IMAGE_MODEL env var).
        api_key: API key (default from IMAGE_API_KEY env var).
        base_url: API base URL (default from IMAGE_BASE_URL env var).
        input_image: Optional input image path for editing.
        width/height: Image dimensions (NVIDIA only).
        steps: Diffusion steps (NVIDIA only).
        cfg_scale: CFG scale (NVIDIA only).
        seed: Random seed for reproducibility (NVIDIA only).
        negative_prompt: What to avoid (NVIDIA only).
        scientific_mode: Append scientific style suffix.

    Returns:
        dict with generation metadata.
    """
    if not prompt or not isinstance(prompt, str):
        raise ValueError("[ERROR] Prompt must be a non-empty string")
    if len(prompt) > MAX_PROMPT_LENGTH:
        raise ValueError(f"[ERROR] Prompt too long: {len(prompt)} chars (max {MAX_PROMPT_LENGTH})")

    default_key, default_url, default_model = get_image_config()
    api_key = api_key or default_key
    base_url = (base_url or default_url).rstrip("/") if (base_url or default_url) else ""
    model = model or default_model

    if _is_nvidia_key(api_key):
        # NVIDIA NIM path
        nv_model = model if model in NVIDIA_MODELS else NVIDIA_DEFAULT_MODEL
        if model != nv_model:
            print(f"[INFO] Model '{model}' not in NVIDIA registry, using {nv_model}")
        image_data = _generate_nvidia(
            prompt=prompt, model=nv_model, api_key=api_key,
            width=width, height=height, steps=steps,
            cfg_scale=cfg_scale, seed=seed,
            negative_prompt=negative_prompt,
            scientific_mode=scientific_mode,
        )
    else:
        # OpenAI-compatible chat/completions path
        url = base_url or DEFAULT_OPENAI_BASE_URL
        image_data = _generate_chat_completions(
            prompt=prompt, model=model, api_key=api_key,
            base_url=url, input_image=input_image,
            scientific_mode=scientific_mode,
        )

    # Save image
    out_dir = Path(output_path).parent
    if str(out_dir) not in ('', '.'):
        out_dir.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'wb') as f:
        f.write(image_data)

    print(f"[OK] Image saved to: {output_path} ({len(image_data)} bytes)")

    return {
        "model": model,
        "output_path": output_path,
        "provider": "nvidia" if _is_nvidia_key(api_key) else "openai-compat",
        "size_bytes": len(image_data),
    }


# ── CLI ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Generate images with auto-detected provider (NVIDIA or OpenAI-compatible)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Examples:
  python generate_image.py "Neural network architecture" -o nn.png
  python generate_image.py "Flowchart" -o flow.png --model agnes-2.0-flash
  python generate_image.py "Add a hat" -o edited.png --input original.png
  python generate_image.py "Circuit" -o circuit.png --no-scientific

Environment variables (all IMAGE_* — fully decoupled from writing model):
  IMAGE_API_KEY       API key (required) — auto-detects provider
  IMAGE_BASE_URL      Base URL for OpenAI-compatible endpoint
  IMAGE_MODEL         Model name (default: {DEFAULT_IMAGE_MODEL})

Provider auto-detection:
  - API key starts with "nvapi-"  → NVIDIA NIM
  - Otherwise                     → OpenAI-compatible chat/completions
        """,
    )

    parser.add_argument("prompt", help="Text description of the image to generate")
    parser.add_argument("-o", "--output", default="generated_image.png", help="Output file path")
    parser.add_argument("--model", "-m", default=None, help="Model ID")
    parser.add_argument("--input", "-i", default=None, help="Input image path for editing")
    parser.add_argument("--width", type=int, default=1024, help="Image width / NVIDIA only")
    parser.add_argument("--height", type=int, default=1024, help="Image height / NVIDIA only")
    parser.add_argument("--steps", type=int, default=None, help="Diffusion steps / NVIDIA only")
    parser.add_argument("--cfg-scale", type=float, default=None, help="CFG scale / NVIDIA only")
    parser.add_argument("--seed", type=int, default=None, help="Random seed / NVIDIA only")
    parser.add_argument("--negative-prompt", default="", help="Negative prompt / NVIDIA only")
    parser.add_argument("--no-scientific", action="store_true", help="Disable scientific style suffix")
    parser.add_argument("--api-key", default=None, help="API key")
    parser.add_argument("--base-url", default=None, help="API base URL")

    args = parser.parse_args()

    try:
        generate_image(
            prompt=args.prompt,
            output_path=args.output,
            model=args.model,
            api_key=args.api_key,
            base_url=args.base_url,
            input_image=args.input,
            width=args.width,
            height=args.height,
            steps=args.steps,
            cfg_scale=args.cfg_scale,
            seed=args.seed,
            negative_prompt=args.negative_prompt,
            scientific_mode=not args.no_scientific,
        )
    except (ValueError, RuntimeError) as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
