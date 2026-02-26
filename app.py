import os
import csv
from io import StringIO
from datetime import datetime
import tempfile

from flask import Flask, render_template, request, jsonify, send_from_directory, send_file
from flask_cors import CORS
from pydub import AudioSegment

# ===============================
# Flask App
# ===============================
app = Flask(__name__)
CORS(app)

# ===============================
# Automated Deployment Proof
# ===============================
APP_VERSION = "2.0"
DEPLOYMENT_METHOD = "GitHub Actions + AWS SSM"
BUILD_ID = (os.environ.get("GITHUB_SHA") or os.environ.get("GITHUB_ACTIONS_SHA") or "local")[:7]
BUILD_TIME = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# ===============================
# Global State
# ===============================
current_directory = None
current_playlist = []
audio_file_map = {}

SUPPORTED_AUDIO_EXTENSIONS = (".mp3", ".wav", ".ogg")
parsed_transcription_data = {}

# ===============================
# Helpers
# ===============================
def parse_log_content(log_content: str):
    """
    Parse CSV or TSV error log
    """
    data = {}
    delimiter = "\t" if log_content.count("\t") > log_content.count(",") else ","
    reader = csv.reader(StringIO(log_content), delimiter=delimiter)

    header = next(reader, None)
    if not header:
        return data

    def col(name):
        try:
            return header.index(name)
        except ValueError:
            return None

    col_audio = col("transcriptFile")
    col_ls = col("longFormStart")
    col_le = col("longFormEnd")
    col_lerr = col("longFormError")
    col_serr = col("shortFormError")
    col_ss = col("shortFormStart")
    col_se = col("shortFormEnd")

    for row in reader:
        if not row or col_audio is None:
            continue

        filename = os.path.basename(row[col_audio])
        segment = {
            "longFormStart": float(row[col_ls]) if col_ls is not None and row[col_ls] else None,
            "longFormEnd": float(row[col_le]) if col_le is not None and row[col_le] else None,
            "longFormError": row[col_lerr] if col_lerr is not None else "",
            "shortFormError": row[col_serr] if col_serr is not None else "",
            "shortFormStart": float(row[col_ss]) if col_ss is not None and row[col_ss] else None,
            "shortFormEnd": float(row[col_se]) if col_se is not None and row[col_se] else None,
        }

        data.setdefault(filename, []).append(segment)

    return data

# ===============================
# Routes
# ===============================
@app.route("/")
def index():
    """
    Main UI with CI/CD proof banner
    """
    proof = {
        "message": "Hello from Automated CI/CD Pipeline!",
        "version": APP_VERSION,
        "deployed_via": DEPLOYMENT_METHOD,
        "build_id": BUILD_ID,
        "build_time": BUILD_TIME,
        "assignment": "Automated EC2 Deployment",
    }
    return render_template("index.html", proof=proof)


@app.route("/health")
def health():
    """
    Health endpoint required by instructor
    """
    return jsonify({
        "status": "healthy",
        "version": APP_VERSION,
        "deployment_method": "automated",
        "deployed_via": DEPLOYMENT_METHOD,
        "build_id": BUILD_ID,
        "timestamp": datetime.now().isoformat(),
    })


@app.route("/select_directory", methods=["POST"])
def select_directory():
    global current_directory, current_playlist, audio_file_map

    path = request.form.get("directory_path")
    if not path or not os.path.isdir(path):
        return jsonify(success=False, message="Invalid directory")

    current_directory = path
    current_playlist = []
    audio_file_map = {}

    for root, _, files in os.walk(path):
        for f in files:
            if f.lower().endswith(SUPPORTED_AUDIO_EXTENSIONS):
                full_path = os.path.join(root, f)
                current_playlist.append(full_path)
                audio_file_map[f] = full_path
                audio_file_map[os.path.splitext(f)[0]] = full_path

    current_playlist.sort()

    return jsonify(
        success=True,
        message=f"Loaded {len(current_playlist)} audio files",
        files_with_info=[
            {
                "name": os.path.basename(p),
                "url": f"/audio_files/{os.path.basename(p)}",
                "error_segments": parsed_transcription_data.get(os.path.basename(p), []),
            }
            for p in current_playlist
        ],
    )


@app.route("/audio_files/<path:filename>")
def serve_audio_file(filename):
    path = audio_file_map.get(filename)
    if not path or not os.path.exists(path):
        return "File not found", 404
    return send_from_directory(os.path.dirname(path), os.path.basename(path))


@app.route("/audio_segment")
def serve_audio_segment():
    filename = request.args.get("file")
    start = request.args.get("start", type=float)
    end = request.args.get("end", type=float)

    if not filename or start is None or end is None:
        return "Missing parameters", 400

    audio_path = audio_file_map.get(filename)
    if not audio_path or not os.path.exists(audio_path):
        return "Audio not found", 404

    audio = AudioSegment.from_file(audio_path)
    duration = len(audio) / 1000

    segment = audio[
        max(0, start - 5) * 1000 :
        min(duration, end + 5) * 1000
    ]

    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
        segment.export(f.name, format="wav")
        return send_file(f.name, mimetype="audio/wav")


@app.route("/upload_log", methods=["POST"])
def upload_log():
    global parsed_transcription_data

    file = request.files.get("log_file")
    if not file:
        return jsonify(success=False, message="No file uploaded")

    parsed_transcription_data = parse_log_content(file.read().decode())
    return jsonify(success=True, message="Log parsed successfully")


@app.route("/status")
def status():
    return jsonify(
        currentDirectory=current_directory,
        files_with_info=[
            {
                "name": os.path.basename(p),
                "url": f"/audio_files/{os.path.basename(p)}",
                "error_segments": parsed_transcription_data.get(os.path.basename(p), []),
            }
            for p in current_playlist
        ],
        logLoaded=bool(parsed_transcription_data),
        version=APP_VERSION,
        deployed_via=DEPLOYMENT_METHOD,
        build_id=BUILD_ID,
    )

# ===============================
# Main
# ===============================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3000)
