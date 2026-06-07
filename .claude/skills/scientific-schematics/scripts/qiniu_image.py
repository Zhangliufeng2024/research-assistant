#!/usr/bin/env python3
"""
Qiniu Cloud (七牛云) /images/generations API helper.

Handles the different request/response format for Kling models on Qiniu Cloud,
including async task polling for Kling models that return task_id.

This module is imported by generate_image.py, generate_schematic_ai.py,
generate_infographic_ai.py, and generate_slide_image_ai.py.
"""

import base64
import json
import os
import sys
import time
import random
from pathlib import Path
from typing import Optional, Dict, Any, List


def is_kling_model(model: str) -> bool:
    """Check if the model is a Qiniu Cloud Kling model."""
    return model.startswith("kling")


def build_images_generations_payload(
    model: str,
    prompt: str,
    styled_prompt: str,
    image_config: Optional[Dict[str, str]] = None,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    negative_prompt: Optional[str] = None,
    input_image_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build request payload for /images/generations endpoint.

    Args:
        model: Model ID (e.g., "kling-v1-5", "gemini-3.0-pro-image-preview")
        prompt: Original user prompt
        styled_prompt: Prompt with style directives prepended
        image_config: Optional dict with aspect_ratio and/or image_size
        temperature: Optional generation temperature (0.0-2.0)
        top_p: Optional nucleus sampling parameter
        negative_prompt: Optional negative prompt (Kling only)
        input_image_url: Optional URL or base64 of reference image (Kling only)

    Returns:
        Request payload dictionary
    """
    payload: Dict[str, Any] = {
        "model": model,
        "prompt": styled_prompt,
    }

    if image_config:
        payload["image_config"] = image_config

    if temperature is not None:
        payload["temperature"] = temperature

    if top_p is not None:
        payload["top_p"] = top_p

    if negative_prompt and is_kling_model(model):
        payload["negative_prompt"] = negative_prompt

    if input_image_url and is_kling_model(model):
        payload["image"] = input_image_url

    return payload


def poll_kling_task(
    base_url: str,
    api_key: str,
    task_id: str,
    max_wait_seconds: int = 300,
    poll_interval: float = 5.0,
    verbose: bool = False,
) -> Dict[str, Any]:
    """
    Poll a Kling async task until completion.

    Args:
        base_url: API base URL (e.g., "https://api.qnaigc.com/v1")
        api_key: API key for authentication
        task_id: Task ID returned by /images/generations
        max_wait_seconds: Maximum time to wait for task completion
        poll_interval: Seconds between polls
        verbose: Print progress info

    Returns:
        Task result dictionary with status and data

    Raises:
        RuntimeError: If task fails or times out
    """
    import requests

    url = f"{base_url}/images/tasks/{task_id}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    start_time = time.time()
    attempt = 0

    while True:
        attempt += 1
        elapsed = time.time() - start_time

        if elapsed > max_wait_seconds:
            raise RuntimeError(
                f"Kling task {task_id} timed out after {max_wait_seconds}s"
            )

        if verbose:
            print(f"[POLL] Checking task {task_id} (attempt {attempt}, {elapsed:.0f}s elapsed)")

        try:
            response = requests.get(url, headers=headers, timeout=30)

            if response.status_code != 200:
                if verbose:
                    print(f"[POLL] HTTP {response.status_code}: {response.text[:200]}")
                time.sleep(poll_interval)
                continue

            result = response.json()
            status = result.get("status", "")

            if verbose:
                print(f"[POLL] Task status: {status}")

            if status == "succeed":
                return result
            elif status == "failed":
                error_msg = result.get("status_message", "Unknown error")
                raise RuntimeError(f"Kling task {task_id} failed: {error_msg}")
            elif status in ("submitted", "processing"):
                time.sleep(poll_interval)
                continue
            else:
                if verbose:
                    print(f"[POLL] Unknown status: {status}, continuing...")
                time.sleep(poll_interval)
                continue

        except requests.exceptions.RequestException as e:
            if verbose:
                print(f"[POLL] Request error: {e}, retrying...")
            time.sleep(poll_interval)
            continue


def extract_image_from_kling_response(
    response_data: Dict[str, Any],
    verbose: bool = False,
) -> Optional[bytes]:
    """
    Extract image bytes from a Qiniu Cloud /images/generations response.

    Handles two cases:
    1. Synchronous response (Gemini models): data[].b64_json
    2. Async response (Kling models): task_id -> poll -> data[].url

    Args:
        response_data: Raw API response dictionary
        verbose: Print debug info

    Returns:
        Image bytes or None
    """
    # Case 1: Synchronous response with b64_json
    data_list = response_data.get("data", [])
    if data_list and isinstance(data_list, list):
        first_item = data_list[0]
        if isinstance(first_item, dict):
            # Direct base64 response
            b64_json = first_item.get("b64_json")
            if b64_json:
                if verbose:
                    print(f"[OK] Found b64_json in response ({len(b64_json)} chars)")
                # Clean whitespace
                b64_clean = b64_json.replace('\n', '').replace('\r', '').replace(' ', '')
                return base64.b64decode(b64_clean)

            # URL response (from task polling)
            url = first_item.get("url")
            if url:
                if verbose:
                    print(f"[OK] Found URL in response: {url[:100]}...")
                return _download_image(url, verbose)

    return None


def _download_image(url: str, verbose: bool = False) -> Optional[bytes]:
    """Download image from URL and return bytes."""
    import requests

    try:
        response = requests.get(url, timeout=60)
        if response.status_code == 200:
            if verbose:
                print(f"[OK] Downloaded image ({len(response.content)} bytes)")
            return response.content
        else:
            if verbose:
                print(f"[ERR] Failed to download image: HTTP {response.status_code}")
            return None
    except Exception as e:
        if verbose:
            print(f"[ERR] Failed to download image: {e}")
        return None


def call_images_generations(
    base_url: str,
    api_key: str,
    model: str,
    styled_prompt: str,
    max_retries: int = 3,
    request_timeout: int = 120,
    poll_timeout: int = 300,
    verbose: bool = False,
    **kwargs,
) -> Optional[bytes]:
    """
    Call /images/generations endpoint and return image bytes.

    Handles both synchronous (Gemini) and async (Kling) responses.

    Args:
        base_url: API base URL (e.g., "https://api.qnaigc.com/v1")
        api_key: API key
        model: Model ID
        styled_prompt: Prompt with style directives
        max_retries: Max retry attempts for the initial request
        request_timeout: Timeout for the initial request in seconds
        poll_timeout: Max wait for Kling async tasks in seconds
        verbose: Print debug info
        **kwargs: Additional params passed to build_images_generations_payload

    Returns:
        Image bytes or None if failed
    """
    import requests

    url = f"{base_url}/images/generations"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = build_images_generations_payload(
        model=model,
        prompt=styled_prompt,
        styled_prompt=styled_prompt,
        **kwargs,
    )

    base_delay = 2
    last_exception = None

    for attempt in range(max_retries):
        if verbose:
            print(f"[GEN] POST {url} (attempt {attempt + 1}/{max_retries})")
            print(f"[GEN] Model: {model}")

        try:
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=request_timeout,
            )

            if response.status_code == 200:
                result = response.json()

                if verbose:
                    print(f"[GEN] Response keys: {list(result.keys())}")

                # Check if this is an async task response (Kling)
                task_id = result.get("task_id")
                if task_id:
                    if verbose:
                        print(f"[GEN] Async task: {task_id}")
                    # Poll until task completes
                    task_result = poll_kling_task(
                        base_url=base_url,
                        api_key=api_key,
                        task_id=task_id,
                        max_wait_seconds=poll_timeout,
                        verbose=verbose,
                    )
                    return extract_image_from_kling_response(task_result, verbose)

                # Synchronous response (Gemini)
                return extract_image_from_kling_response(result, verbose)

            elif response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else base_delay * (2 ** attempt) + random.uniform(0, 1)
                if verbose:
                    print(f"[WARN] Rate limited (429). Retrying in {delay:.1f}s")
                time.sleep(delay)
                last_exception = RuntimeError(f"Rate limited (HTTP 429): {response.text[:200]}")

            elif response.status_code >= 500:
                delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                if verbose:
                    print(f"[WARN] Server error ({response.status_code}). Retrying in {delay:.1f}s")
                time.sleep(delay)
                last_exception = RuntimeError(f"Server error (HTTP {response.status_code}): {response.text[:200]}")

            else:
                raise RuntimeError(
                    f"API Error (HTTP {response.status_code}): {response.text[:500]}"
                )

        except requests.exceptions.Timeout:
            delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
            if verbose:
                print(f"[WARN] Request timed out. Retrying in {delay:.1f}s")
            time.sleep(delay)
            last_exception = RuntimeError("Request timed out")

        except requests.exceptions.RequestException as e:
            delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
            if verbose:
                print(f"[WARN] Request failed: {e}. Retrying in {delay:.1f}s")
            time.sleep(delay)
            last_exception = RuntimeError(f"Request failed: {e}")

    raise last_exception or RuntimeError("Request failed after all retries")
