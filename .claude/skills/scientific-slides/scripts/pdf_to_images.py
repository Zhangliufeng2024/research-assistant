#!/usr/bin/env python3
"""
PDF to Images Converter for Presentations

Converts presentation PDFs to images for visual inspection and review.
Supports multiple output formats and resolutions.

Uses PyMuPDF (fitz) as the primary conversion method - no external
dependencies required (no poppler, ghostscript, or ImageMagick needed).
"""

import sys
import gc
import argparse
from pathlib import Path
from typing import Optional, List

# Fix Windows console encoding for emoji characters
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Try to import pymupdf (preferred - no external dependencies)
try:
    import fitz  # PyMuPDF
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False


class PDFToImagesConverter:
    """Converts PDF presentations to images."""
    
    def __init__(
        self,
        pdf_path: str,
        output_prefix: str,
        dpi: int = 150,
        format: str = 'jpg',
        first_page: Optional[int] = None,
        last_page: Optional[int] = None
    ):
        self.pdf_path = Path(pdf_path)
        self.output_prefix = output_prefix
        self.dpi = dpi
        self.format = format.lower()
        self.first_page = first_page
        self.last_page = last_page
        
        # Validate format
        if self.format not in ['jpg', 'jpeg', 'png']:
            raise ValueError(f"Unsupported format: {format}. Use jpg or png.")
    
    def convert(self) -> List[Path]:
        """Convert PDF to images using PyMuPDF."""
        if not self.pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {self.pdf_path}")
        
        print(f"Converting: {self.pdf_path.name}")
        print(f"Output prefix: {self.output_prefix}")
        print(f"DPI: {self.dpi}")
        print(f"Format: {self.format}")
        
        if HAS_PYMUPDF:
            return self._convert_with_pymupdf()
        else:
            raise RuntimeError(
                "PyMuPDF not installed. Install it with:\n"
                "  pip install pymupdf\n\n"
                "PyMuPDF is a self-contained library - no external dependencies needed."
            )
    
    def _convert_with_pymupdf(self) -> List[Path]:
        """Convert using PyMuPDF library (no external dependencies)."""
        print("Using PyMuPDF (no external dependencies required)...")

        # Open the PDF
        doc = fitz.open(self.pdf_path)

        # --- Size guards ---
        file_size_mb = self.pdf_path.stat().st_size / (1024 * 1024)
        total_pages = doc.page_count

        if file_size_mb > 100:
            print(f"[WARN] PDF is {file_size_mb:.1f} MB ({total_pages} pages). This may consume significant memory.")

        # Adaptive DPI: reduce for large PDFs to prevent memory exhaustion
        effective_dpi = self.dpi
        if file_size_mb > 50 and self.dpi > 150:
            effective_dpi = 150
            print(f"[INFO] Large PDF ({file_size_mb:.1f} MB): reducing DPI from {self.dpi} to {effective_dpi}")
        elif file_size_mb > 20 and self.dpi > 200:
            effective_dpi = 200
            print(f"[INFO] Medium PDF ({file_size_mb:.1f} MB): reducing DPI from {self.dpi} to {effective_dpi}")

        # Page count guard: limit to 100 pages to prevent memory issues
        max_pages = 100
        if total_pages > max_pages:
            print(f"[WARN] PDF has {total_pages} pages. Limiting conversion to first {max_pages} pages.")

        # Determine page range
        start_page = (self.first_page - 1) if self.first_page else 0
        end_page = self.last_page if self.last_page else doc.page_count
        end_page = min(end_page, start_page + max_pages)

        # Calculate zoom factor from DPI (72 DPI is the base)
        zoom = effective_dpi / 72
        matrix = fitz.Matrix(zoom, zoom)

        output_files = []
        output_dir = Path(self.output_prefix).parent
        output_dir.mkdir(parents=True, exist_ok=True)

        for page_num in range(start_page, end_page):
            page = doc[page_num]

            # Render page to pixmap
            pixmap = page.get_pixmap(matrix=matrix)

            # Determine output path
            output_path = Path(f"{self.output_prefix}-{page_num + 1:03d}.{self.format}")

            # Save the image
            if self.format in ['jpg', 'jpeg']:
                pixmap.save(str(output_path), output="jpeg")
            else:
                pixmap.save(str(output_path), output="png")

            # Free pixmap memory immediately
            pixmap = None
            page = None

            output_files.append(output_path)
            print(f"  Created: {output_path.name}")

            # Periodic garbage collection for large documents
            if len(output_files) % 10 == 0:
                gc.collect()

        doc.close()
        return output_files


def main():
    parser = argparse.ArgumentParser(
        description='Convert presentation PDFs to images',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s presentation.pdf slides
    → Creates slides-001.jpg, slides-002.jpg, ...
  
  %(prog)s presentation.pdf output/slide --dpi 300 --format png
    → Creates output/slide-001.png, slide-002.png, ... at high resolution
  
  %(prog)s presentation.pdf review/s --first 5 --last 10
    → Converts only slides 5-10

Output:
  Images are named: PREFIX-001.FORMAT, PREFIX-002.FORMAT, etc.
  
Resolution:
  - 150 DPI: Good for screen review (default)
  - 200 DPI: Higher quality for detailed inspection
  - 300 DPI: Print quality (larger files)

Requirements:
  Install PyMuPDF (no external dependencies needed):
    pip install pymupdf
        """
    )
    
    parser.add_argument(
        'pdf_path',
        help='Path to PDF presentation'
    )
    
    parser.add_argument(
        'output_prefix',
        help='Output filename prefix (e.g., "slides" or "output/slide")'
    )
    
    parser.add_argument(
        '--dpi', '-r',
        type=int,
        default=150,
        help='Resolution in DPI (default: 150)'
    )
    
    parser.add_argument(
        '--format', '-f',
        choices=['jpg', 'jpeg', 'png'],
        default='jpg',
        help='Output format (default: jpg)'
    )
    
    parser.add_argument(
        '--first',
        type=int,
        help='First page to convert (1-indexed)'
    )
    
    parser.add_argument(
        '--last',
        type=int,
        help='Last page to convert (1-indexed)'
    )
    
    args = parser.parse_args()
    
    # Create output directory if needed
    output_dir = Path(args.output_prefix).parent
    if output_dir != Path('.'):
        output_dir.mkdir(parents=True, exist_ok=True)
    
    # Convert
    try:
        converter = PDFToImagesConverter(
            pdf_path=args.pdf_path,
            output_prefix=args.output_prefix,
            dpi=args.dpi,
            format=args.format,
            first_page=args.first,
            last_page=args.last
        )
        
        output_files = converter.convert()
        
        print()
        print("=" * 60)
        print(f"✅ Success! Created {len(output_files)} image(s)")
        print("=" * 60)
        
        if output_files:
            print(f"\nFirst image: {output_files[0]}")
            print(f"Last image: {output_files[-1]}")
            
            # Calculate total size
            total_size = sum(f.stat().st_size for f in output_files)
            size_mb = total_size / (1024 * 1024)
            print(f"Total size: {size_mb:.2f} MB")
            
            print("\nNext steps:")
            print("  1. Review images for layout issues")
            print("  2. Check for text overflow or element overlap")
            print("  3. Verify readability from distance")
            print("  4. Document issues with slide numbers")
        
        sys.exit(0)
        
    except Exception as e:
        print(f"\n❌ Error: {str(e)}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
