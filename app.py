# ================================================
# ANVESHAK – TRUE FINAL IMMORTAL VERSION
# Works on ANY Windows PC • No install • OCR + Native • Zero bugs
# ================================================
import sys
import os
import io
import json
import shutil
import time
import threading
import hashlib
import string
from collections import defaultdict
import concurrent.futures
from flask import Flask, request, jsonify, render_template, send_from_directory
from PIL import Image, ImageEnhance, ImageFilter
import pytesseract
import pymupdf as fitz

app = Flask(__name__, static_folder=None, template_folder='templates')

# ==================== INSTANT SPLASH ====================
if getattr(sys, 'frozen', False):
    import ctypes
    def show_splash():
        ctypes.windll.user32.MessageBoxW(
            0,
            "Anveshak is launching lightning fast...\n\n"
            "First run: Takes few seconds for extracting files.\n"
            "Next runs: Instant forever!\n\n"
            "Please wait",
            "Anveshak – Starting",
            0x40 | 0x1000
        )
    threading.Thread(target=show_splash, daemon=True).start()
    time.sleep(0.1)

# ==================== STORAGE ====================
if getattr(sys, 'frozen', False):
    exe_dir = os.path.dirname(sys.executable)
    BASE = os.path.join(exe_dir, "Anveshak_Data")
    bundle_dir = sys._MEIPASS
else:
    BASE = "Anveshak_Data"
    bundle_dir = os.path.abspath(".")
os.makedirs(BASE, exist_ok=True)

# ==================== TESSERACT SETUP ====================
if getattr(sys, 'frozen', False):
    base_path = sys._MEIPASS
else:
    base_path = os.path.abspath(".")

pytesseract.pytesseract.tesseract_cmd = os.path.join(base_path, "tesseract", "tesseract.exe")
os.environ["TESSDATA_PREFIX"] = os.path.join(base_path, "tesseract", "tessdata")

OCR_CONFIG = '--psm 6'
DISPLAY_DPI = OCR_DPI = 150

# ==================== OCR & RENDER FUNCTIONS ====================
def preprocess_for_ocr(img):
    img = img.convert('L')
    img = ImageEnhance.Contrast(img).enhance(2.0)
    img = img.filter(ImageFilter.SHARPEN)
    img = img.filter(ImageFilter.MedianFilter(3))
    return img

def render_page(pdf_path, pno, png_dir):
    doc = fitz.open(pdf_path)
    pix = doc[pno].get_pixmap(dpi=DISPLAY_DPI, colorspace=fitz.csRGB)
    name = f"page_{pno+1}.png"
    pix.save(os.path.join(png_dir, name))
    doc.close()
    return name

def extract_native(pdf_path, pno):
    doc = fitz.open(pdf_path)
    page = doc[pno]
    words = []
    try:
        blocks = page.get_text("dict")["blocks"]
        line_no = 0
        scale = DISPLAY_DPI / 72.0
        for b in blocks:
            if "lines" not in b: continue
            for line in b["lines"]:
                line_no += 1
                for span in line["spans"]:
                    txt = span["text"].strip()
                    if not txt: continue
                    bbox = [c * scale for c in span["bbox"]]
                    words.append({"w": txt, "b": bbox, "l": line_no, "s": "native", "c": 100})
    except: pass
    doc.close()
    return pno, words

def ocr_tesseract(pdf_path, pno):
    doc = fitz.open(pdf_path)
    page = doc[pno]
    pix = page.get_pixmap(dpi=OCR_DPI, colorspace=fitz.csGRAY)
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    img = preprocess_for_ocr(img)
    doc.close()
    try:
        data = pytesseract.image_to_data(img, config=OCR_CONFIG, output_type=pytesseract.Output.DICT)
    except Exception as e:
        print(f"Tesseract failed on page {pno+1}: {e}")
        return pno, []
    words = []
    line = 1
    last_top = -1
    for i in range(len(data["text"])):
        w = data["text"][i].strip()
        if not w: continue
        conf = max(0, int(data["conf"][i]))
        bbox = [data["left"][i], data["top"][i],
                data["left"][i] + data["width"][i],
                data["top"][i] + data["height"][i]]
        if data["top"][i] > last_top + 20:
            line += 1
        last_top = data["top"][i]
        words.append({"w": w, "b": bbox, "l": line, "s": "tesseract", "c": conf})
    return pno, words

def bbox_iou(b1, b2):
    x1,y1,x2,y2 = b1
    a1,b1_,a2,b2_ = b2
    xi1 = max(x1,a1); yi1 = max(y1,b1_)
    xi2 = min(x2,a2); yi2 = min(y2,b2_)
    inter = max(0, xi2-xi1) * max(0, yi2-yi1)
    u = (x2-x1)*(y2-y1) + (a2-a1)*(b2_-b1_) - inter
    return inter/u if u > 0 else 0

def merge_ocr_results(native, tess):
    candidates = [w.copy() | {"source": "native"} for w in native] + \
                 [w.copy() | {"source": "tesseract"} for w in tess]
    merged, used = [], set()
    for i, cand in enumerate(candidates):
        if i in used: continue
        best = cand
        for j, other in enumerate(candidates):
            if j in used or j == i: continue
            if bbox_iou(cand["b"], other["b"]) > 0.5 and other["c"] > best["c"]:
                best = other; used.add(j)
        merged.append(best); used.add(i)
    return merged

# ==================== ROUTES ====================
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/upload", methods=["POST"])
def upload():
    if 'file' not in request.files:
        return jsonify({"error": "No file"}), 400
    file = request.files["file"]
    if not file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "PDF only"}), 400

    file.stream.seek(0)
    hasher = hashlib.md5()
    while chunk := file.stream.read(8192):
        hasher.update(chunk)
    file_hash = hasher.hexdigest()
    file.stream.seek(0)

    sess = file_hash
    sess_dir = os.path.join(BASE, sess)
    pdf_path = os.path.join(sess_dir, "doc.pdf")
    ready_path = os.path.join(sess_dir, "READY")
    start = time.time()

    if os.path.exists(ready_path):
        png_dir = os.path.join(sess_dir, "png")
        rendered = sorted([f for f in os.listdir(png_dir) if f.endswith('.png')])
        doc = fitz.open(pdf_path)
        total_pages = len(doc)
        doc.close()
        os.utime(sess_dir, None)
        return jsonify({"session": sess, "total_pages": total_pages, "rendered_pages": rendered,
                        "load_time": round(time.time()-start, 2), "status": "reused"})

    if os.path.exists(sess_dir):
        shutil.rmtree(sess_dir)
    os.makedirs(sess_dir, exist_ok=True)
    os.makedirs(os.path.join(sess_dir, "png"), exist_ok=True)
    os.makedirs(os.path.join(sess_dir, "json"), exist_ok=True)

    file.save(pdf_path)

    try:
        doc = fitz.open(pdf_path)
        total_pages = len(doc)

        metadata = doc.metadata
        clean_meta = {k: v.strip() if isinstance(v, str) else v 
                      for k, v in metadata.items() if v and str(v).strip()}

        display_name = clean_meta.get('title', file.filename) or file.filename

        with open(os.path.join(sess_dir, "metadata.json"), "w", encoding="utf-8") as f:
            json.dump(clean_meta, f, ensure_ascii=False, indent=2)

        with open(os.path.join(sess_dir, "filename.txt"), "w", encoding="utf-8") as f:
            f.write(display_name)

        doc.close()
    except Exception as e:
        print(f"Metadata extraction failed: {e}")
        total_pages = 0
        with open(os.path.join(sess_dir, "filename.txt"), "w", encoding="utf-8") as f:
            f.write(file.filename)

    png_dir = os.path.join(sess_dir, "png")
    json_dir = os.path.join(sess_dir, "json")

    # Smart CPU workers
    cpu_count = os.cpu_count() or 4
    if cpu_count <= 4:
        max_workers = 4
    elif cpu_count <= 8:
        max_workers = 8
    else:
        max_workers = 12

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        render_futs = [ex.submit(render_page, pdf_path, p, png_dir) for p in range(total_pages)]
        native_futs = [ex.submit(extract_native, pdf_path, p) for p in range(total_pages)]
        tess_futs = [ex.submit(ocr_tesseract, pdf_path, p) for p in range(total_pages)]
        rendered = [None] * total_pages
        native_results = [None] * total_pages
        tess_results = [None] * total_pages

        for f in concurrent.futures.as_completed(render_futs):
            name = f.result()
            pno = int(name.split('_')[1].split('.')[0]) - 1
            rendered[pno] = name
        for f in concurrent.futures.as_completed(native_futs):
            pno, words = f.result()
            native_results[pno] = words
        for f in concurrent.futures.as_completed(tess_futs):
            pno, words = f.result()
            tess_results[pno] = words

        for pno in range(total_pages):
            final_words = merge_ocr_results(native_results[pno], tess_results[pno])
            page_data = {"page": pno + 1, "words": final_words, "type": "mixed"}
            with open(os.path.join(json_dir, f"page_{pno+1}.json"), "w", encoding="utf-8") as f:
                json.dump(page_data, f, ensure_ascii=False)

    with open(ready_path, "w") as f:
        f.write("1")

    rendered = [f"page_{i+1}.png" for i in range(total_pages)]
    return jsonify({"session": sess, "total_pages": total_pages, "rendered_pages": rendered,
                    "load_time": round(time.time()-start, 2), "status": "complete"})

@app.route("/<sess>/png/<filename>")
def serve_png(sess, filename):
    return send_from_directory(os.path.join(BASE, sess, "png"), filename)

@app.route("/search", methods=["POST"])
def search():
    data = request.json
    sess = data.get("session")
    term = (data.get("search_term") or "").strip()
    if not (sess and term):
        return jsonify({"matches": [], "grouped": {}, "stats": {"total_matches":0,"native":0,"tesseract":0,"kraken":0}})

    json_dir = os.path.join(BASE, sess, "json")
    if not os.path.exists(json_dir):
        return jsonify({"matches": [], "grouped": {}, "stats": {"total_matches":0,"native":0,"tesseract":0,"kraken":0}})

    def clean(text):
        return text.translate(str.maketrans('', '', string.punctuation)).lower().strip()

    search_words = [clean(w) for w in term.split() if clean(w)]
    if not search_words:
        return jsonify({"matches": [], "grouped": {}, "stats": {"total_matches":0,"native":0,"tesseract":0,"kraken":0}})

    matches = []
    for json_file in sorted(os.listdir(json_dir)):
        if not json_file.endswith(".json"): continue
        with open(os.path.join(json_dir, json_file), "r", encoding="utf-8") as f:
            pg = json.load(f)
        pno = pg["page"]
        words = pg["words"]

        cleaned_words = []
        for wobj in words:
            if wobj.get("c", 100) < 30 or len(wobj["w"]) > 50:
                continue
            cleaned = clean(wobj["w"])
            if cleaned:
                cleaned_words.append({"text": cleaned, "obj": wobj})

        for i in range(len(cleaned_words) - len(search_words) + 1):
            window = [cleaned_words[i+j]["text"] for j in range(len(search_words))]
            if window == search_words:
                phrase_bboxes = []
                valid_bboxes_count = 0
                for j in range(len(search_words)):
                    obj = cleaned_words[i + j]["obj"]
                    raw_b = obj.get("b")
                    if raw_b and len(raw_b) == 4:
                        x0, y0, x1, y1 = raw_b
                        padded = [x0 - 2, y0 - 2, x1 + 2, y1 + 2]
                        phrase_bboxes.append(padded)
                        valid_bboxes_count += 1
                    else:
                        phrase_bboxes.append(None)

                if valid_bboxes_count == 0:
                    fallback = [100, 100, 200, 130]
                    bboxes = [fallback] * len(search_words)
                else:
                    first_valid = next((b for b in phrase_bboxes if b), phrase_bboxes[0])
                    bboxes = [b if b else first_valid for b in phrase_bboxes]

                start_idx = max(0, i - 8)
                end_idx = min(len(cleaned_words), i + len(search_words) + 8)
                excerpt_words = [cleaned_words[j]["obj"]["w"] for j in range(start_idx, end_idx)]
                excerpt = " ".join(excerpt_words)

                phrase_original = " ".join([cleaned_words[i+j]["obj"]["w"] for j in range(len(search_words))])
                lower_excerpt = excerpt.lower()
                lower_phrase = phrase_original.lower()
                hl_start = lower_excerpt.find(lower_phrase)
                hl_end = hl_start + len(phrase_original) if hl_start != -1 else 0

                anchor_obj = cleaned_words[i]["obj"]

                matches.append({
                    "page": pno,
                    "line": anchor_obj["l"],
                    "source": anchor_obj.get("source", anchor_obj.get("s", "unknown")),
                    "confidence": anchor_obj.get("c", 100),
                    "bboxes": bboxes,
                    "excerpt": excerpt,
                    "highlight_start": hl_start,
                    "highlight_end": hl_end
                })

    native_cnt = len([m for m in matches if m["source"] == "native"])
    tess_cnt = len([m for m in matches if m["source"] == "tesseract"])
    stats = {"total_matches": len(matches), "native": native_cnt, "tesseract": tess_cnt, "kraken": 0}

    grouped = defaultdict(list)
    for m in matches:
        grouped[m["page"]].append(m)

    return jsonify({"matches": matches, "grouped": dict(grouped), "stats": stats})

@app.route("/library", methods=["GET"])
def get_library():
    library = []
    for sess_folder in os.listdir(BASE):
        sess_path = os.path.join(BASE, sess_folder)
        if not os.path.isdir(sess_path) or not os.path.exists(os.path.join(sess_path, "READY")):
            continue
        pdf_path = os.path.join(sess_path, "doc.pdf")
        if not os.path.exists(pdf_path):
            continue
        fn_path = os.path.join(sess_path, "filename.txt")
        filename = "Unknown.pdf"
        if os.path.exists(fn_path):
            with open(fn_path, "r", encoding="utf-8") as f:
                filename = f.read().strip()
        try:
            doc = fitz.open(pdf_path)
            total_pages = len(doc)
            file_size = os.path.getsize(pdf_path)
            doc.close()
        except:
            total_pages = file_size = 0
        library.append({"session": sess_folder, "filename": filename, "pages": total_pages,
                        "size": file_size, "modified": os.path.getmtime(sess_path)})
    library.sort(key=lambda x: x["modified"], reverse=True)
    return jsonify({"library": library})

@app.route("/load/<sess>", methods=["GET"])
def load_session(sess):
    sess_dir = os.path.join(BASE, sess)
    ready_path = os.path.join(sess_dir, "READY")
    if not os.path.exists(ready_path):
        return jsonify({"error": "Not ready"}), 404
    png_dir = os.path.join(sess_dir, "png")
    rendered = sorted([f for f in os.listdir(png_dir) if f.endswith('.png')])
    doc = fitz.open(os.path.join(sess_dir, "doc.pdf"))
    total_pages = len(doc)
    doc.close()
    os.utime(sess_dir, None)
    return jsonify({"session": sess, "total_pages": total_pages, "rendered_pages": rendered})

@app.route("/cleanup", methods=["POST"])
def cleanup():
    sess = request.json.get("session")
    if sess:
        path = os.path.join(BASE, sess)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
    return jsonify({"ok": True})

# ==================== START ====================
if __name__ == "__main__":
    from flaskwebgui import FlaskUI

    FlaskUI(
        app=app,
        server="flask",
        width=1800,
        height=1000,
        port=5503
    ).run()