"""Quick OCR test."""
import sys
sys.path.insert(0, "D:\\opencode")

# Try to run OCR on a minimal image
import io
import base64

# Minimal valid PNG: 10x10 white image with some text
# This is a base64 encoded simple PNG
minimal_png = (
    "iVBORw0KGgoAAAANSUhEUgAAAAoAAAAKCAYAAACNMs+9AAAAFUlE"
    "QVR42mNk+P9/zw0IwEhDQK8AALXEAz2r22yMAAAAAElFTkSuQmCC"
)

# Actually create a test image with text using PIL
try:
    from PIL import Image, ImageDraw, ImageFont
    
    img = Image.new('RGB', (400, 200), color='white')
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 24)
    except:
        font = ImageFont.load_default()
    
    draw.text((20, 20), "Indomaret", fill='black', font=font)
    draw.text((20, 60), "Bayar: Rp50.000", fill='black', font=font)
    draw.text((20, 100), "Kembali: Rp0", fill='black', font=font)
    
    img_bytes = io.BytesIO()
    img.save(img_bytes, format='PNG')
    img_bytes = img_bytes.getvalue()
    
    print(f"Created test image: {len(img_bytes)} bytes")
    
    # Test OCR
    from app.services.ocr import read_lines
    
    lines = read_lines(img_bytes)
    print(f"OCR result: {len(lines)} lines")
    for line in lines:
        print(f"  [{line['top']:.0f}] {line['text']} ({line['score']:.2f})")
        
except ImportError as e:
    print(f"PIL not available: {e}")
except Exception as e:
    print(f"Test error: {e}")
    import traceback
    traceback.print_exc()
