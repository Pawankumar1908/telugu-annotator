from flask import Flask, render_template, request, redirect, session, jsonify
import pandas as pd
from datetime import datetime
import os

from indic_transliteration import sanscript
from indic_transliteration.sanscript import transliterate

app = Flask(__name__)
app.secret_key = "change_this_secret"

DATA = "data"
USERS = f"{DATA}/users.csv"
REPO = f"{DATA}/repository.csv"
NEW = f"{DATA}/new_annotations.csv"
ENC = "utf-8-sig"


# ---------- SAFE CSV ----------
def safe_read(path):
    if not os.path.exists(path):
        return pd.DataFrame()
    try:
        df = pd.read_csv(path, encoding=ENC)
    except:
        df = pd.read_csv(path, encoding="latin1")
    df.columns = df.columns.str.strip()
    return df


def ensure_file(path, columns):
    if not os.path.exists(path):
        pd.DataFrame(columns=columns).to_csv(path, index=False, encoding=ENC)


ensure_file(
    NEW,
    ["serial_no", "proverb_telugu", "proverb_english",
     "meaning_english", "keywords", "annotator", "timestamp"]
)
ensure_file(
    REPO,
    ["serial_no", "proverb_telugu", "proverb_english",
     "meaning_english", "keywords", "annotator"]
)


# ---------- HELPERS ----------
def normalize(text):
    return " ".join(str(text).lower().strip().split())


def to_roman(text):
    try:
        return transliterate(text, sanscript.TELUGU, sanscript.ITRANS).lower()
    except:
        return text.lower()


def authenticate(username, password):
    df = safe_read(USERS)
    if df.empty:
        return False
    return ((df.iloc[:, 0] == username) & (df.iloc[:, 1] == password)).any()


def next_serial():
    df = safe_read(NEW)
    if df.empty:
        return 1
    return int(df["serial_no"].astype(int).max()) + 1


def contribution_count(name):
    total = 0
    df_new = safe_read(NEW)
    df_repo = safe_read(REPO)

    if "annotator" in df_new.columns:
        total += len(df_new[df_new["annotator"] == name])
    if "annotator" in df_repo.columns:
        total += len(df_repo[df_repo["annotator"] == name])

    return total


def is_admin():
    return session.get("role") == "admin"


# ---------- VERIFY ----------
@app.route("/verify", methods=["POST"])
def verify():
    value = request.json.get("value", "")
    key = normalize(to_roman(value))

    for src in [REPO, NEW]:
        df = safe_read(src)
        for _, row in df.iterrows():
            tel = normalize(to_roman(row.get("proverb_telugu", "")))
            eng = normalize(row.get("proverb_english", ""))
            if key == tel or key == eng:
                return jsonify({"status": "exists", "data": row.to_dict()})

    return jsonify({"status": "new", "roman": to_roman(value)})


# ---------- LOGIN ----------
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        name = request.form["annotator"].strip()

        if authenticate(username, password):
            session.clear()
            session["username"] = username
            session["annotator"] = name
            session["role"] = "admin" if username == "admin" else "annotator"
            return redirect("/welcome")

        return render_template("login.html", error="Invalid credentials")

    return render_template("login.html")


# ---------- WELCOME ----------
@app.route("/welcome")
def welcome():
    if "annotator" not in session:
        return redirect("/")
    if is_admin():
        return redirect("/admin/dashboard")
    return render_template("welcome.html", name=session["annotator"])


# ---------- ANNOTATE ----------
@app.route("/annotate", methods=["GET", "POST"])
def annotate():
    if "annotator" not in session or is_admin():
        return redirect("/")

    name = session["annotator"]
    count = contribution_count(name)
    message = None

    if request.method == "POST":
        tel = request.form.get("proverb_telugu", "").strip()
        eng = request.form.get("proverb_english", "").strip()

        if not tel or not eng:
            message = "❌ Please verify proverb before submitting"
            return render_template("annotate.html", name=name, count=count, message=message)

        df = safe_read(NEW)

        new_row = {
            "serial_no": next_serial(),
            "proverb_telugu": tel,
            "proverb_english": normalize(eng),
            "meaning_english": request.form.get("meaning_english", ""),
            "keywords": request.form.get("keywords", ""),
            "annotator": name,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
        df.to_csv(NEW, index=False, encoding=ENC)

        count += 1
        message = "✅ Annotation saved successfully"

    return render_template("annotate.html", name=name, count=count, message=message)


# ---------- ADMIN ----------
@app.route("/admin/dashboard")
def admin_dashboard():
    if not is_admin():
        return redirect("/")
    return render_template("admin_dashboard.html")


@app.route("/admin/annotators")
def admin_annotators():
    if not is_admin():
        return redirect("/")
    df = safe_read(NEW)
    stats = df["annotator"].value_counts().to_dict() if "annotator" in df.columns else {}
    return render_template("admin_annotators.html", stats=stats)


@app.route("/admin/repository")
def admin_repository():
    if not is_admin():
        return redirect("/")
    df = safe_read(REPO)
    records = df.to_dict(orient="records")
    return render_template("admin_repository.html", records=records, total=len(records))


@app.route("/admin/new")
def admin_new():
    if not is_admin():
        return redirect("/")
    df = safe_read(NEW)
    records = df.to_dict(orient="records")
    return render_template("admin_new.html", records=records, total=len(records))


@app.route("/admin/approve/<int:serial_no>")
def admin_approve(serial_no):
    if not is_admin():
        return redirect("/")

    new_df = safe_read(NEW)
    new_df["serial_no"] = new_df["serial_no"].astype(int)

    row = new_df[new_df["serial_no"] == serial_no]
    if row.empty:
        return redirect("/admin/new")

    repo_df = safe_read(REPO)
    repo_df = pd.concat([repo_df, row], ignore_index=True)
    repo_df.to_csv(REPO, index=False, encoding=ENC)

    new_df = new_df[new_df["serial_no"] != serial_no]
    new_df.to_csv(NEW, index=False, encoding=ENC)

    return redirect("/admin/new")


# ---------- LOGOUT ----------
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


if __name__ == "__main__":
    app.run()
