import os
import re
import csv
from io import StringIO
from flask import Flask, render_template, request, jsonify, send_from_directory, send_file
from flask_cors import CORS
from pydub import AudioSegment
import tempfile
from datetime import datetime

app = Flask(__name__)
CORS(app)

# ===============================
# Automated Deployment Proof
# ===============================
APP_VERSION = "2.0"
DEPLOYMENT_METHOD = "GitHub Actions + AWS SSM"
BUILD_ID = os.environ.get("GITHUB_SHA", "local")[:7]
BUILD_TIME = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# ===============================
# Global variables
# ===============================
current_directory = None
current_playlist = []
audio_file_map = {}
SUPPORTED_AUDIO_EXTENSIONS = ('.mp3', '.wav', '.ogg')

parsed_transcription_data = {}
csv_error_data = []
csv_file_loaded = False


def time_to_seconds(time_str):
    try:
        if ':' in time_str:
            parts = time_str.split(':')
            if len(parts) == 3:
                h, m, s = map(float, parts)
                return h * 3600 + m * 60 + s
            elif len(parts) == 2:
                m, s = map(float, parts)
                return m * 60 + s
        return float(time_str)
    except Exception:
        return 0.0


def parse_log_content(log_content):
    data = {}
    delimiter = '\t' if log_content.count('\t') > log_content.count(',') else ','
    reader = csv.reader(StringIO(log_content), delimiter=delimiter)
    header = next(reader, None)

    def col(name):
        try:
            return header.index(name)
        except ValueError:
            return None

    col_audio = col('transcriptFile')
    col_ls = col('longFormStart')
    col_le = col('longFormEnd')
    col_lerr = col('longFormError')
    col_serr = col('shortFormError')
    col_ss = col('shortFormStart')
    col_se = col('shortFormEnd')

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
            "shortFormEnd": float(row[col_se]) if col_se is not None and row[col_se] else None
        }
        data.setdefault(filename, []).append(segment)

    return data


@app.route('/')
def index():
    """
    Main page with automated deployment proof
    """
    proof = {
        "message": "Hello from Automated CI/CD Pipeline!",
        "version": APP_VERSION,
        "deployed_via": DEPLOYMENT_METHOD,
        "build_id": BUILD_ID,
        "build_time": BUILD_TIME,
        "assignment": "Automated EC2 Deployment"
    }
    return render_template("index.html", proof=proof)


@app.route('/health')
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
        "timestamp": datetime.now().isoformat()
    })


@app.route('/audio_files/<path:filename>')
def serve_audio_file(filename):
    if filename in audio_file_map:
        path = audio_file_map[filename]
        return send_from_directory(os.path.dirname(path), os.path.basename(path))
    return "File not found", 404


@app.route('/audio_segment')
def serve_audio_segment():
    filename = request.args.get('file')
    start = request.args.get('start', type=float)
    end = request.args.get('end', type=float)

    if not (filename and start is not None and end is not None):
        return "Missing parameters", 400

    audio_path = audio_file_map.get(filename)
    if not audio_path or not os.path.exists(audio_path):
        return "Audio not found", 404

    audio = AudioSegment.from_file(audio_path)
    duration = len(audio) / 1000
    seg = audio[max(0, start - 5) * 1000: min(duration, end + 5) * 1000]

    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
        seg.export(f.name, format="wav")
        return send_file(f.name, mimetype="audio/wav")


@app.route('/select_directory', methods=['POST'])
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
                full = os.path.join(root, f)
                current_playlist.append(full)
                audio_file_map[f] = full
                audio_file_map[os.path.splitext(f)[0]] = full

    current_playlist.sort()
    return jsonify(success=True, message=f"Loaded {len(current_playlist)} audio files")


@app.route('/upload_log', methods=['POST'])
def upload_log():
    global parsed_transcription_data
    file = request.files.get("log_file")
    if not file:
        return jsonify(success=False, message="No file")

    parsed_transcription_data = parse_log_content(file.read().decode())
    return jsonify(success=True, message="Log parsed successfully")


@app.route('/status')
def status():
    return jsonify(
        directory=current_directory,
        files=len(current_playlist),
        logLoaded=bool(parsed_transcription_data),
        version=APP_VERSION,
        deployed_via=DEPLOYMENT_METHOD,
        build_id=BUILD_ID
    )


def auto_load_data():
    pass


if __name__ == "__main__":
    auto_load_data()
    app.run(host="0.0.0.0", port=3000)
