#!/usr/bin/env python3
"""
AI-powered scientific schematic generation using Nano Banana Pro.

This script uses a smart iterative refinement approach:
1. Generate initial image with Nano Banana Pro
2. AI quality review using Gemini 3 Pro for scientific critique
3. Only regenerate if quality is below threshold for document type
4. Repeat until quality meets standards (max iterations)

Requirements:
    - LLM_API_KEY environment variable
    - requests library

Usage:
    python generate_schematic_ai.py "Create a flowchart showing CONSORT participant flow" -o flowchart.png
    python generate_schematic_ai.py "Neural network architecture diagram" -o architecture.png --iterations 2
    python generate_schematic_ai.py "Simple block diagram" -o diagram.png --doc-type poster
"""

import argparse
import base64
import json
import os
import random
import sys
# Fix Windows console encoding for emoji/non-ASCII characters
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import time
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

try:
    import requests
except ImportError:
    print("Error: requests library not found. Install with: pip install requests")
    sys.exit(1)


# Try to load .env file from multiple potential locations
def _load_env_file():
    """Load .env file from current directory, parent directories, or package directory.
    
    Returns True if a .env file was found and loaded, False otherwise.
    Note: This does NOT override existing environment variables.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        return False  # python-dotenv not installed
    
    # Try current working directory first
    env_path = Path.cwd() / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=False)
        return True
        
    # Try parent directories (up to 5 levels)
    cwd = Path.cwd()
    for _ in range(5):
        env_path = cwd / ".env"
        if env_path.exists():
            load_dotenv(dotenv_path=env_path, override=False)
            return True
        cwd = cwd.parent
        if cwd == cwd.parent:  # Reached root
            break
    
    # Try the package's parent directory (research-assistant project root)
    script_dir = Path(__file__).resolve().parent
    for _ in range(5):
        env_path = script_dir / ".env"
        if env_path.exists():
            load_dotenv(dotenv_path=env_path, override=False)
            return True
        script_dir = script_dir.parent
        if script_dir == script_dir.parent:
            break
            
    return False


class ScientificSchematicGenerator:
    """Generate scientific schematics using AI with smart iterative refinement.
    
    Uses Gemini 3 Pro for quality review to determine if regeneration is needed.
    Multiple passes only occur if the generated schematic doesn't meet the
    quality threshold for the target document type.
    """
    
    # Quality thresholds by document type (score out of 10)
    # Higher thresholds for more formal publications
    QUALITY_THRESHOLDS = {
        "journal": 8.5,      # Nature, Science, etc. - highest standards
        "conference": 8.0,   # Conference papers - high standards
        "poster": 7.0,       # Academic posters - good quality
        "presentation": 6.5, # Slides/talks - clear but less formal
        "report": 7.5,       # Technical reports - professional
        "grant": 8.0,        # Grant proposals - must be compelling
        "thesis": 8.0,       # Dissertations - formal academic
        "preprint": 7.5,     # arXiv, etc. - good quality
        "default": 7.5,      # Default threshold
    }
    
    # Load unified style directives from sci_figure_style module
    @staticmethod
    def _load_style_directives() -> str:
        """Load style directives from sci_figure_style, with fallback."""
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
        # Fallback: hardcoded Okabe-Ito palette
        return """VISUAL STYLE (mandatory):
- Color palette: Okabe-Ito colorblind-safe — use these hex colors in order:
  #E69F00, #56B4E9, #009E73, #0072B2, #D55E00, #CC79A7, #F0E444
- Font: Arial or Helvetica (sans-serif only), no serif fonts
- Font sizes: 8-9pt for labels, 10pt bold for titles
- Axes/borders: show only bottom and left, no top/right border
- Line width: 0.5pt for structure, 1.0pt for data/connections
- Background: solid white, no gradients or textures
- No drop shadows, no 3D effects, no decorative elements
- Clean, minimal, publication-ready aesthetic
- White space: adequate margins, not cramped"""

    SCIENTIFIC_DIAGRAM_GUIDELINES = """
Create a high-quality scientific diagram with these requirements:

VISUAL QUALITY:
- Clean white or light background (no textures or gradients)
- High contrast for readability and printing
- Professional, publication-ready appearance
- Sharp, clear lines and text
- Adequate spacing between elements to prevent crowding

TYPOGRAPHY:
- Clear, readable sans-serif fonts (Arial, Helvetica style)
- Minimum 10pt font size for all labels
- Consistent font sizes throughout
- All text horizontal or clearly readable
- No overlapping text

SCIENTIFIC STANDARDS:
- Accurate representation of concepts
- Clear labels for all components
- Include scale bars, legends, or axes where appropriate
- Use standard scientific notation and symbols
- Include units where applicable

ACCESSIBILITY:
- Colorblind-friendly color palette (use Okabe-Ito colors if using color)
- High contrast between elements
- Redundant encoding (shapes + colors, not just colors)
- Works well in grayscale

LAYOUT:
- Logical flow (left-to-right or top-to-bottom)
- Clear visual hierarchy
- Balanced composition
- Appropriate use of whitespace
- No clutter or unnecessary decorative elements

IMPORTANT - NO FIGURE NUMBERS:
- Do NOT include "Figure 1:", "Fig. 1", or any figure numbering in the image
- Do NOT add captions or titles like "Figure: ..." at the top or bottom
- Figure numbers and captions are added separately in the document/LaTeX
- The diagram should contain only the visual content itself
"""

    # Unified style directives (loaded once at class definition time)
    _UNIFIED_STYLE = _load_style_directives()
    
    def __init__(self, api_key: Optional[str] = None, verbose: bool = False):
        """
        Initialize the generator.
        
        Args:
            api_key: API key (or use LLM_API_KEY env var)
            verbose: Print detailed progress information
        """
        # Priority: 1) explicit api_key param, 2) model_config, 3) environment variable, 4) .env file
        self.api_key = api_key or os.getenv("IMAGE_API_KEY")

        # If not found in environment, try loading from .env file
        if not self.api_key:
            _load_env_file()
            self.api_key = os.getenv("IMAGE_API_KEY")

        if not self.api_key:
            raise ValueError(
                "IMAGE_API_KEY not found. Please either:\n"
                "  1. Set the IMAGE_API_KEY environment variable\n"
                "  2. Add IMAGE_API_KEY to your .env file\n"
                "  3. Pass api_key parameter to the constructor"
            )

        self.verbose = verbose
        self._last_error = None  # Track last error for better reporting
        self.base_url = os.environ.get("IMAGE_BASE_URL", "https://openrouter.ai/api/v1")
        self.image_model = os.getenv("IMAGE_MODEL", "agnes-2.0-flash")
        self.review_model = os.getenv("IMAGE_REVIEW_MODEL", "agnes-2.0-flash")
        
    def _log(self, message: str):
        """Log message if verbose mode is enabled."""
        if self.verbose:
            print(f"[{time.strftime('%H:%M:%S')}] {message}")
    
    def _make_request(self, model: str, messages: List[Dict[str, Any]],
                     modalities: Optional[List[str]] = None,
                     max_retries: int = 3) -> Dict[str, Any]:
        """
        Make a request to LLM API with retry and exponential backoff.

        Args:
            model: Model identifier
            messages: List of message dictionaries
            modalities: Optional list of modalities (e.g., ["image", "text"])
            max_retries: Maximum number of retry attempts (default: 3)

        Returns:
            API response as dictionary
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/research-assistant",
            "X-Title": "Scientific Schematic Generator"
        }

        payload = {
            "model": model,
            "messages": messages
        }

        if modalities:
            payload["modalities"] = modalities

        base_delay = 2
        last_exception = None

        for attempt in range(max_retries):
            self._log(f"Making request to {model} (attempt {attempt + 1}/{max_retries})...")

            try:
                response = requests.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=120
                )

                # Try to get response body even on error
                try:
                    response_json = response.json()
                except json.JSONDecodeError:
                    response_json = {"raw_text": response.text[:500]}

                # Success
                if response.status_code == 200:
                    return response_json

                # Parse error detail
                error_detail = response_json.get("error", response_json)

                # 429 Rate Limited - retry with backoff
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    if retry_after:
                        wait = float(retry_after)
                    else:
                        wait = base_delay * (2 ** attempt) + random.uniform(0, 1)
                    self._log(f"Rate limited (429). Waiting {wait:.1f}s before retry...")
                    time.sleep(wait)
                    last_exception = RuntimeError(f"Rate limited (HTTP 429): {error_detail}")
                    continue

                # 5xx Server Error - retry with backoff
                if response.status_code >= 500:
                    wait = base_delay * (2 ** attempt) + random.uniform(0, 1)
                    self._log(f"Server error (HTTP {response.status_code}). Waiting {wait:.1f}s before retry...")
                    time.sleep(wait)
                    last_exception = RuntimeError(f"Server error (HTTP {response.status_code}): {error_detail}")
                    continue

                # 4xx Client Error (except 429) - do NOT retry
                self._log(f"Client error (HTTP {response.status_code}): {error_detail}")
                raise RuntimeError(f"API request failed (HTTP {response.status_code}): {error_detail}")

            except requests.exceptions.Timeout:
                wait = base_delay * (2 ** attempt) + random.uniform(0, 1)
                self._log(f"Request timed out. Waiting {wait:.1f}s before retry...")
                time.sleep(wait)
                last_exception = RuntimeError("API request timed out after 120 seconds")
                continue

            except requests.exceptions.RequestException as e:
                wait = base_delay * (2 ** attempt) + random.uniform(0, 1)
                self._log(f"Request failed: {e}. Waiting {wait:.1f}s before retry...")
                time.sleep(wait)
                last_exception = RuntimeError(f"API request failed: {str(e)}")
                continue

        # All retries exhausted
        raise last_exception or RuntimeError("API request failed after all retries")
    
    def _extract_image_from_response(self, response: Dict[str, Any]) -> Optional[bytes]:
        """
        Extract base64-encoded image from API response.
        
        For Nano Banana Pro, images are returned in the 'images' field of the message,
        not in the 'content' field.
        
        Args:
            response: API response dictionary
            
        Returns:
            Image bytes or None if not found
        """
        try:
            choices = response.get("choices", [])
            if not choices:
                self._log("No choices in response")
                return None
            
            message = choices[0].get("message", {})
            
            # IMPORTANT: Nano Banana Pro returns images in the 'images' field
            images = message.get("images", [])
            if images and len(images) > 0:
                self._log(f"Found {len(images)} image(s) in 'images' field")
                
                # Get first image
                first_image = images[0]
                if isinstance(first_image, dict):
                    # Extract image_url
                    if first_image.get("type") == "image_url":
                        url = first_image.get("image_url", {})
                        if isinstance(url, dict):
                            url = url.get("url", "")
                        
                        if url and url.startswith("data:image"):
                            # Extract base64 data after comma
                            if "," in url:
                                base64_str = url.split(",", 1)[1]
                                # Clean whitespace
                                base64_str = base64_str.replace('\n', '').replace('\r', '').replace(' ', '')
                                self._log(f"Extracted base64 data (length: {len(base64_str)})")
                                return base64.b64decode(base64_str)
            
            # Fallback: check content field (for other models or future changes)
            content = message.get("content", "")
            
            if self.verbose:
                self._log(f"Content type: {type(content)}, length: {len(str(content))}")
            
            # Handle string content
            if isinstance(content, str) and "data:image" in content:
                import re
                match = re.search(r'data:image/[^;]+;base64,([A-Za-z0-9+/=\n\r]+)', content, re.DOTALL)
                if match:
                    base64_str = match.group(1).replace('\n', '').replace('\r', '').replace(' ', '')
                    self._log(f"Found image in content field (length: {len(base64_str)})")
                    return base64.b64decode(base64_str)
            
            # Handle list content
            if isinstance(content, list):
                for i, block in enumerate(content):
                    if isinstance(block, dict) and block.get("type") == "image_url":
                        url = block.get("image_url", {})
                        if isinstance(url, dict):
                            url = url.get("url", "")
                        if url and url.startswith("data:image") and "," in url:
                            base64_str = url.split(",", 1)[1].replace('\n', '').replace('\r', '').replace(' ', '')
                            self._log(f"Found image in content block {i}")
                            return base64.b64decode(base64_str)
            
            self._log("No image data found in response")
            return None
            
        except Exception as e:
            self._log(f"Error extracting image: {str(e)}")
            import traceback
            if self.verbose:
                traceback.print_exc()
            return None
    
    def _image_to_base64(self, image_path: str) -> str:
        """
        Convert image file to base64 data URL.
        
        Args:
            image_path: Path to image file
            
        Returns:
            Base64 data URL string
        """
        with open(image_path, "rb") as f:
            image_data = f.read()
        
        # Determine image type from extension
        ext = Path(image_path).suffix.lower()
        mime_type = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp"
        }.get(ext, "image/png")
        
        base64_data = base64.b64encode(image_data).decode("utf-8")
        return f"data:{mime_type};base64,{base64_data}"
    
    def generate_image(self, prompt: str) -> Optional[bytes]:
        """
        Generate an image using Nano Banana Pro.
        
        Args:
            prompt: Description of the diagram to generate
            
        Returns:
            Image bytes or None if generation failed
        """
        self._last_error = None  # Reset error
        
        messages = [
            {
                "role": "user",
                "content": prompt
            }
        ]
        
        try:
            response = self._make_request(
                model=self.image_model,
                messages=messages,
                modalities=["image", "text"]
            )
            
            # Debug: print response structure if verbose
            if self.verbose:
                self._log(f"Response keys: {response.keys()}")
                if "error" in response:
                    self._log(f"API Error: {response['error']}")
                if "choices" in response and response["choices"]:
                    msg = response["choices"][0].get("message", {})
                    self._log(f"Message keys: {msg.keys()}")
                    # Show content preview without printing huge base64 data
                    content = msg.get("content", "")
                    if isinstance(content, str):
                        preview = content[:200] + "..." if len(content) > 200 else content
                        self._log(f"Content preview: {preview}")
                    elif isinstance(content, list):
                        self._log(f"Content is list with {len(content)} items")
                        for i, item in enumerate(content[:3]):
                            if isinstance(item, dict):
                                self._log(f"  Item {i}: type={item.get('type')}")
            
            # Check for API errors in response
            if "error" in response:
                error_msg = response["error"]
                if isinstance(error_msg, dict):
                    error_msg = error_msg.get("message", str(error_msg))
                self._last_error = f"API Error: {error_msg}"
                print(f"鉁?{self._last_error}")
                return None
            
            image_data = self._extract_image_from_response(response)
            if image_data:
                self._log(f"鉁?Generated image ({len(image_data)} bytes)")
            else:
                self._last_error = "No image data in API response - model may not support image generation"
                self._log(f"鉁?{self._last_error}")
                # Additional debug info when image extraction fails
                if self.verbose and "choices" in response:
                    msg = response["choices"][0].get("message", {})
                    self._log(f"Full message structure: {json.dumps({k: type(v).__name__ for k, v in msg.items()})}")
            
            return image_data
        except RuntimeError as e:
            self._last_error = str(e)
            self._log(f"鉁?Generation failed: {self._last_error}")
            return None
        except Exception as e:
            self._last_error = f"Unexpected error: {str(e)}"
            self._log(f"鉁?Generation failed: {self._last_error}")
            import traceback
            if self.verbose:
                traceback.print_exc()
            return None
    
    def review_image(self, image_path: str, original_prompt: str, 
                    iteration: int, doc_type: str = "default",
                    max_iterations: int = 2) -> Tuple[str, float, bool]:
        """
        Review generated image using Gemini 3 Pro for quality analysis.
        
        Uses Gemini 3 Pro's superior vision and reasoning capabilities to
        evaluate the schematic quality and determine if regeneration is needed.
        
        Args:
            image_path: Path to the generated image
            original_prompt: Original user prompt
            iteration: Current iteration number
            doc_type: Document type (journal, poster, presentation, etc.)
            max_iterations: Maximum iterations allowed
            
        Returns:
            Tuple of (critique text, quality score 0-10, needs_improvement bool)
        """
        # Use Gemini 3 Pro for review - excellent vision and analysis
        image_data_url = self._image_to_base64(image_path)
        
        # Get quality threshold for this document type
        threshold = self.QUALITY_THRESHOLDS.get(doc_type.lower(), 
                                                 self.QUALITY_THRESHOLDS["default"])
        
        review_prompt = f"""You are an expert reviewer evaluating a scientific diagram for publication quality.

ORIGINAL REQUEST: {original_prompt}

DOCUMENT TYPE: {doc_type} (quality threshold: {threshold}/10)
ITERATION: {iteration}/{max_iterations}

Carefully evaluate this diagram on these criteria:

1. **Scientific Accuracy** (0-2 points)
   - Correct representation of concepts
   - Proper notation and symbols
   - Accurate relationships shown

2. **Clarity and Readability** (0-2 points)
   - Easy to understand at a glance
   - Clear visual hierarchy
   - No ambiguous elements

3. **Label Quality** (0-2 points)
   - All important elements labeled
   - Labels are readable (appropriate font size)
   - Consistent labeling style

4. **Layout and Composition** (0-2 points)
   - Logical flow (top-to-bottom or left-to-right)
   - Balanced use of space
   - No overlapping elements

5. **Professional Appearance** (0-2 points)
   - Publication-ready quality
   - Clean, crisp lines and shapes
   - Appropriate colors/contrast

RESPOND IN THIS EXACT FORMAT:
SCORE: [total score 0-10]

STRENGTHS:
- [strength 1]
- [strength 2]

ISSUES:
- [issue 1 if any]
- [issue 2 if any]

VERDICT: [ACCEPTABLE or NEEDS_IMPROVEMENT]

If score >= {threshold}, the diagram is ACCEPTABLE for {doc_type} publication.
If score < {threshold}, mark as NEEDS_IMPROVEMENT with specific suggestions."""

        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": review_prompt
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": image_data_url
                        }
                    }
                ]
            }
        ]
        
        try:
            # Use Gemini 3 Pro for high-quality review
            response = self._make_request(
                model=self.review_model,
                messages=messages
            )
            
            # Extract text response
            choices = response.get("choices", [])
            if not choices:
                return "Image generated successfully", 8.0, False
            
            message = choices[0].get("message", {})
            content = message.get("content", "")
            
            # Check reasoning field (Nano Banana Pro puts analysis here)
            reasoning = message.get("reasoning", "")
            if reasoning and not content:
                content = reasoning
            
            if isinstance(content, list):
                # Extract text from content blocks
                text_parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                content = "\n".join(text_parts)
            
            # Try to extract score
            score = 6.0  # Default score if extraction fails (conservative)
            import re

            # Look for SCORE: X at start of line (anchored)
            score_match = re.search(r'^SCORE:\s*(\d+(?:\.\d+)?)', content, re.MULTILINE | re.IGNORECASE)
            if score_match:
                score = float(score_match.group(1))
            else:
                # Fallback: look for any score pattern
                score_match = re.search(r'(?:score|rating|quality)[:\s]+(\d+(?:\.\d+)?)\s*(?:/\s*10)?', content, re.IGNORECASE)
                if score_match:
                    score = float(score_match.group(1))

            # Clamp score to 0-10
            score = max(0.0, min(10.0, score))
            
            # Determine if improvement is needed based on verdict or score
            needs_improvement = False
            if "NEEDS_IMPROVEMENT" in content.upper():
                needs_improvement = True
            elif score < threshold:
                needs_improvement = True
            
            self._log(f"鉁?Review complete (Score: {score}/10, Threshold: {threshold}/10)")
            self._log(f"  Verdict: {'Needs improvement' if needs_improvement else 'Acceptable'}")
            
            return (content if content else "Image generated successfully", 
                    score, 
                    needs_improvement)
        except Exception as e:
            print(f"[WARN] Image review failed: {e}, assuming needs improvement", file=sys.stderr)
            # Review failure means we cannot verify quality - assume needs improvement
            return (f"Review failed: {e}", 5.0, True)
    
    def _extract_issues(self, critique: str) -> str:
        """Extract only the ISSUES section from critique."""
        import re
        match = re.search(r'ISSUES?:?\s*\n(.*?)(?:\n\s*(?:VERDICT|SCORE|STRENGTHS)|\Z)', critique, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()[:500]
        # Fallback: return first 500 chars
        return critique[:500]

    def improve_prompt(self, original_prompt: str, critique: str,
                      iteration: int) -> str:
        """
        Improve the generation prompt based on critique.
        
        Args:
            original_prompt: Original user prompt
            critique: Review critique from previous iteration
            iteration: Current iteration number
            
        Returns:
            Improved prompt for next generation
        """
        issues = self._extract_issues(critique)
        improved_prompt = f"""{self.SCIENTIFIC_DIAGRAM_GUIDELINES}

{self._UNIFIED_STYLE}

USER REQUEST: {original_prompt}

ITERATION {iteration}: Based on previous feedback, address these specific improvements:
{issues}

Generate an improved version that addresses all the critique points while maintaining scientific accuracy and professional quality."""
        
        return improved_prompt
    
    def generate_iterative(self, user_prompt: str, output_path: str,
                          iterations: int = 2, 
                          doc_type: str = "default") -> Dict[str, Any]:
        """
        Generate scientific schematic with smart iterative refinement.
        
        Only regenerates if the quality score is below the threshold for the
        specified document type. This saves API calls and time when the first
        generation is already good enough.
        
        Args:
            user_prompt: User's description of desired diagram
            output_path: Path to save final image
            iterations: Maximum refinement iterations (default: 2, max: 2)
            doc_type: Document type for quality threshold (journal, poster, etc.)
            
        Returns:
            Dictionary with generation results and metadata
        """
        output_path = Path(output_path)
        output_dir = output_path.parent
        output_dir.mkdir(parents=True, exist_ok=True)
        
        base_name = output_path.stem
        extension = output_path.suffix or ".png"
        
        # Get quality threshold for this document type
        threshold = self.QUALITY_THRESHOLDS.get(doc_type.lower(), 
                                                 self.QUALITY_THRESHOLDS["default"])
        
        results = {
            "user_prompt": user_prompt,
            "doc_type": doc_type,
            "quality_threshold": threshold,
            "iterations": [],
            "final_image": None,
            "final_score": 0.0,
            "success": False,
            "early_stop": False,
            "early_stop_reason": None
        }
        
        current_prompt = f"""{self.SCIENTIFIC_DIAGRAM_GUIDELINES}

{self._UNIFIED_STYLE}

USER REQUEST: {user_prompt}

Generate a publication-quality scientific diagram that meets all the guidelines above."""
        
        print(f"\n{'='*60}")
        print(f"Generating Scientific Schematic")
        print(f"{'='*60}")
        print(f"Description: {user_prompt}")
        print(f"Document Type: {doc_type}")
        print(f"Quality Threshold: {threshold}/10")
        print(f"Max Iterations: {iterations}")
        print(f"Output: {output_path}")
        print(f"{'='*60}\n")
        
        for i in range(1, iterations + 1):
            print(f"\n[Iteration {i}/{iterations}]")
            print("-" * 40)
            
            # Generate image
            print(f"Generating image...")
            image_data = self.generate_image(current_prompt)
            
            if not image_data:
                error_msg = getattr(self, '_last_error', 'Image generation failed - no image data returned')
                print(f"鉁?Generation failed: {error_msg}")
                results["iterations"].append({
                    "iteration": i,
                    "success": False,
                    "error": error_msg
                })
                continue
            
            # Save iteration image
            iter_path = output_dir / f"{base_name}_v{i}{extension}"
            with open(iter_path, "wb") as f:
                f.write(image_data)
            print(f"鉁?Saved: {iter_path}")
            
            # Review image using Gemini 3 Pro
            print(f"Reviewing image with Gemini 3 Pro...")
            critique, score, needs_improvement = self.review_image(
                str(iter_path), user_prompt, i, doc_type, iterations
            )
            print(f"鉁?Score: {score}/10 (threshold: {threshold}/10)")
            
            # Save iteration results
            iteration_result = {
                "iteration": i,
                "image_path": str(iter_path),
                "prompt": current_prompt,
                "critique": critique,
                "score": score,
                "needs_improvement": needs_improvement,
                "success": True
            }
            results["iterations"].append(iteration_result)
            
            # Check if quality is acceptable - STOP EARLY if so
            if not needs_improvement:
                print(f"\n鉁?Quality meets {doc_type} threshold ({score} >= {threshold})")
                print(f"  No further iterations needed!")
                results["final_image"] = str(iter_path)
                results["final_score"] = score
                results["success"] = True
                results["early_stop"] = True
                results["early_stop_reason"] = f"Quality score {score} meets threshold {threshold} for {doc_type}"
                break
            
            # If this is the last iteration, we're done regardless
            if i == iterations:
                print(f"\n鈿?Maximum iterations reached")
                results["final_image"] = str(iter_path)
                results["final_score"] = score
                results["success"] = True
                break
            
            # Quality below threshold - improve prompt for next iteration
            print(f"\n鈿?Quality below threshold ({score} < {threshold})")
            print(f"Improving prompt based on feedback...")
            current_prompt = self.improve_prompt(user_prompt, critique, i + 1)
        
        # If the loop ended without success, report the failure clearly
        if not results["success"]:
            failed_iters = [r for r in results["iterations"] if not r.get("success")]
            errors = [r.get("error", "unknown") for r in failed_iters]
            print(f"\n[ERROR] All {iterations} iteration(s) failed. Errors: {errors}", file=sys.stderr)

        # Copy final version to output path
        if results["success"] and results["final_image"]:
            final_iter_path = Path(results["final_image"])
            if final_iter_path != output_path:
                import shutil
                shutil.copy(final_iter_path, output_path)
                print(f"\n鉁?Final image: {output_path}")
        
        # Save review log
        log_path = output_dir / f"{base_name}_review_log.json"
        with open(log_path, "w") as f:
            json.dump(results, f, indent=2)
        print(f"鉁?Review log: {log_path}")
        
        print(f"\n{'='*60}")
        print(f"Generation Complete!")
        print(f"Final Score: {results['final_score']}/10")
        if results["early_stop"]:
            print(f"Iterations Used: {len([r for r in results['iterations'] if r.get('success')])}/{iterations} (early stop)")
        print(f"{'='*60}\n")
        
        return results


def main():
    """Command-line interface."""
    parser = argparse.ArgumentParser(
        description="Generate scientific schematics using AI with smart iterative refinement",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate a flowchart for a journal paper
  python generate_schematic_ai.py "CONSORT participant flow diagram" -o flowchart.png --doc-type journal
  
  # Generate neural network architecture for presentation (lower threshold)
  python generate_schematic_ai.py "Transformer encoder-decoder architecture" -o transformer.png --doc-type presentation
  
  # Generate with custom max iterations for poster
  python generate_schematic_ai.py "Biological signaling pathway" -o pathway.png --iterations 2 --doc-type poster
  
  # Verbose output
  python generate_schematic_ai.py "Circuit diagram" -o circuit.png -v

Document Types (quality thresholds):
  journal      8.5/10  - Nature, Science, peer-reviewed journals
  conference   8.0/10  - Conference papers
  thesis       8.0/10  - Dissertations, theses
  grant        8.0/10  - Grant proposals
  preprint     7.5/10  - arXiv, bioRxiv, etc.
  report       7.5/10  - Technical reports
  poster       7.0/10  - Academic posters
  presentation 6.5/10  - Slides, talks
  default      7.5/10  - General purpose

Note: Multiple iterations only occur if quality is BELOW the threshold.
      If the first generation meets the threshold, no extra API calls are made.

Environment:
  IMAGE_API_KEY         API key (required)
  IMAGE_BASE_URL        API base URL (optional)
  IMAGE_MODEL           Image generation model (default: agnes-2.0-flash)
  IMAGE_REVIEW_MODEL    Quality review model (default: agnes-2.0-flash)
        """
    )
    
    parser.add_argument("prompt", help="Description of the diagram to generate")
    parser.add_argument("-o", "--output", required=True, 
                       help="Output image path (e.g., diagram.png)")
    parser.add_argument("--iterations", type=int, default=2,
                       help="Maximum refinement iterations (default: 2, max: 2)")
    parser.add_argument("--doc-type", default="default",
                       choices=["journal", "conference", "poster", "presentation", 
                               "report", "grant", "thesis", "preprint", "default"],
                       help="Document type for quality threshold (default: default)")
    parser.add_argument("--api-key", help="API key (or set LLM_API_KEY)")
    parser.add_argument("-v", "--verbose", action="store_true",
                       help="Verbose output")
    
    args = parser.parse_args()
    
    # Check for API key
    api_key = args.api_key or os.getenv("IMAGE_API_KEY")
    if not api_key:
        print("Error: IMAGE_API_KEY environment variable not set")
        print("\nSet it with:")
        print("  export IMAGE_API_KEY='your_api_key'")
        print("\nOr provide via --api-key flag")
        sys.exit(1)
    
    # Validate iterations - enforce max of 2
    if args.iterations < 1 or args.iterations > 2:
        print("Error: Iterations must be between 1 and 2")
        sys.exit(1)
    
    try:
        generator = ScientificSchematicGenerator(api_key=api_key, verbose=args.verbose)
        results = generator.generate_iterative(
            user_prompt=args.prompt,
            output_path=args.output,
            iterations=args.iterations,
            doc_type=args.doc_type
        )
        
        if results["success"]:
            print(f"\n鉁?Success! Image saved to: {args.output}")
            if results.get("early_stop"):
                print(f"  (Completed in {len([r for r in results['iterations'] if r.get('success')])} iteration(s) - quality threshold met)")
            sys.exit(0)
        else:
            print(f"\n鉁?Generation failed. Check review log for details.")
            sys.exit(1)
    except Exception as e:
        print(f"\n鉁?Error: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()

