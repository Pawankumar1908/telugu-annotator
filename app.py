from flask import Flask, render_template, request, redirect, session, jsonify, abort
import pandas as pd
from datetime import datetime
import os
import unicodedata

from indic_transliteration import sanscript
from indic_transliteration.sanscript import transliterate

app = Flask(__name__)
app.secret_key = "change_this_secret_key"

# ---------------- PATHS ----------------
DATA = "data"
USERS = f"{DATA}/users.csv"
REPO = f"{DATA}/repository.csv"
NEW = f"{DATA}/new_annotations.csv"
ENC = "utf-8-sig"

os.makedirs(DATA, exist_ok=True)

# ---------------- FILE INIT ----------------
def ensure_file(path, columns):
    if not os.path.exists(path):
        pd.DataFrame(columns=columns).to_csv(path, index=False, encoding=ENC)

ensure_file(USERS, ["username", "password"])
ensure_file(REPO, ["proverb_telugu", "proverb_english", "meaning_english", "keywords"])
ensure_file(
    NEW,
    ["serial_no", "proverb_telugu", "proverb_english",
     "meaning_english", "keywords", "annotator", "timestamp"]
)

# ---------------- HELPERS ----------------
def safe_read(path):
    try:
        return pd.read_csv(path, encoding=ENC)
    except:
        return pd.read_csv(path, encoding="latin1")

def normalize(text):
    return " ".join(str(text).lower().strip().split())

def normalize_telugu(text):
    text = unicodedata.normalize("NFC", str(text))
    try:
        return normalize(transliterate(text, sanscript.TELUGU, sanscript.ITRANS))
    except:
        return normalize(text)

def next_serial():
    df = safe_read(NEW)
    return 1 if df.empty else int(df["serial_no"].max()) + 1

def is_admin():
    return session.get("role") == "admin"

# ---------------- AUTH ----------------
def authenticate(username, password):
    df = safe_read(USERS)
    df["username"] = df["username"].astype(str).str.strip().str.lower()
    df["password"] = df["password"].astype(str).str.strip()
    return ((df["username"] == username) & (df["password"] == password)).any()

# ---------------- DUPLICATE CHECK ----------------
@app.route("/verify", methods=["POST"])
def verify():
    value = request.json.get("value", "")
    key = normalize_telugu(value)

    for src in [REPO, NEW]:
        df = safe_read(src)
        if df.empty:
            continue

        for _, row in df.iterrows():
            tel = normalize_telugu(row.get("proverb_telugu", ""))
            eng = normalize(row.get("proverb_english", ""))

            if key == tel or key == eng:
                return jsonify({"status": "exists", "data": row.to_dict()})

    return jsonify({"status": "new"})

# ---------------- LOGIN ----------------
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"].strip().lower()
        password = request.form["password"].strip()
        name = request.form["annotator"].strip()

        if authenticate(username, password):
            session.clear()
            session["username"] = username
            session["annotator"] = name
            session["role"] = "admin" if username == "admin" else "annotator"
            return redirect("/welcome")

        return render_template("login.html", error="Invalid credentials")

    return render_template("login.html")

# ---------------- WELCOME ----------------
@app.route("/welcome")
def welcome():
    if "annotator" not in session:
        return redirect("/")
    if is_admin():
        return redirect("/admin/dashboard")
    return render_template("welcome.html", name=session["annotator"])

# ---------------- ANNOTATE ----------------
@app.route("/annotate", methods=["GET", "POST"])
def annotate():
    if "annotator" not in session or is_admin():
        return redirect("/")

    name = session["annotator"]
    df = safe_read(NEW)
    count = len(df[df["annotator"] == name])

    if request.method == "POST":
        new_row = {
            "serial_no": next_serial(),
            "proverb_telugu": request.form["proverb_telugu"],
            "proverb_english": normalize(request.form["proverb_english"]),
            "meaning_english": request.form["meaning_english"],
            "keywords": request.form["keywords"],
            "annotator": name,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
        df.to_csv(NEW, index=False, encoding=ENC)
        count += 1

    return render_template("annotate.html", name=name, count=count)

# ---------------- ADMIN DASHBOARD ----------------
@app.route("/admin/dashboard")
def admin_dashboard():
    if not is_admin():
        return redirect("/")
    return render_template("admin_dashboard.html")

# ---------------- ADMIN ANNOTATORS ----------------
@app.route("/admin/annotators")
def admin_annotators():
    if not is_admin():
        return redirect("/")

    df = safe_read(NEW)
    stats = (
        df.groupby("annotator")
        .size()
        .reset_index(name="contributions")
        .to_dict(orient="records")
    )

    return render_template("admin_annotators.html", stats=stats)

# ---------------- ADMIN REPOSITORY ----------------
@app.route("/admin/repository")
def admin_repository():
    if not is_admin():
        return redirect("/")

    df = safe_read(REPO)
    records = df.to_dict(orient="records")
    total = len(records)

    return render_template(
        "admin_repository.html",
        records=records,
        total=total
    )

# ---------------- ADMIN NEW ----------------
@app.route("/admin/new")
def admin_new():
    if not is_admin():
        return redirect("/")

    df = safe_read(NEW)
    records = df.to_dict(orient="records")
    total = len(records)

    return render_template(
        "admin_new.html",
        records=records,
        total=total
    )

# ---------------- ADMIN APPROVE ----------------
@app.route("/admin/approve/<int:serial_no>")
def admin_approve(serial_no):
    if not is_admin():
        return redirect("/")

    new_df = safe_read(NEW)
    row = new_df[new_df["serial_no"] == serial_no]

    if row.empty:
        abort(404)

    repo_df = safe_read(REPO)
    repo_df = pd.concat(
        [repo_df, row.drop(columns=["serial_no", "annotator", "timestamp"])],
        ignore_index=True
    )

    repo_df.to_csv(REPO, index=False, encoding=ENC)
    new_df = new_df[new_df["serial_no"] != serial_no]
    new_df.to_csv(NEW, index=False, encoding=ENC)

    return redirect("/admin/new")

# ---------------- SWITCH ROLE ----------------
@app.route("/switch-to-annotator", methods=["POST"])
def switch_to_annotator():
    if session.get("role") == "admin":
        session["role"] = "annotator"
    return redirect("/annotate")

# ---------------- LOGOUT ----------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# ---------------- RUN ----------------
if __name__ == "__main__":
    app.run()
