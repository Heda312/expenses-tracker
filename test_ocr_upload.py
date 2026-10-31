"""Quick OCR test with uploaded file."""
import sys
import os
sys.path.insert(0, "D:\\opencode")

# Test OCR on first uploaded file in data/uploads if exists
upload_dir = "D:\\opencode\\data\\uploads"

if os.path.exists(upload_dir):
    files = [f for f in os.listdir(upload_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))]
    if files:
        print(f"Found files in uploads: {files}")
        # Test first file
        test_file = os.path.join(upload_dir, files[0])
        with open(test_file, "rb") as f:
            content = f.read()
        print(f"Testing OCR on: {test_file} ({len(content)} bytes)")
        
        from app.services.ocr import read_lines, OcrError
        
        try:
            lines = read_lines(content)
            print(f"OCR result: {len(lines)} lines")
            for line in lines[:15]:
                print(f"  [{line['top']:4.0f}] {line['text']} (score: {line.get('score', 0):.2f})")
        except OcrError as e:
            print(f"OCR error: {e}")
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
    else:
        print("No image files in uploads folder")
else:
    print(f"Upload folder not found: {upload_dir}")
