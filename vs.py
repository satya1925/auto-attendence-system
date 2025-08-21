# merged_app_auto.py — All-in-one Attendance System
# Auto Attendance: type RegNo or Scan QR -> auto fetch -> live face match -> auto save
# Dark + neon-styled UI; full Reports; enhanced Tools.

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk
import cv2, sqlite3, os, qrcode, face_recognition, shutil
from datetime import datetime
import pandas as pd
from pyzbar.pyzbar import decode  # for QR scanning

# ---------- CONFIG ----------
LOGO_FILE = "logo.png"
DB_FILE   = "students.db"
APP_TITLE = "Central University of Andhra Pradesh - Attendance System"
DEVELOPER_TEXT = "Developed by Satya Durga Rao"

TOLERANCE   = 0.4   # lower = stricter
REQ_CONSEC  = 5     # consecutive matching frames to confirm
CAM_WIDTH   = 480
CAM_HEIGHT  = 360

# ---------- DB ----------
def get_conn(): 
    return sqlite3.connect(DB_FILE)

def init_db():
    os.makedirs("photos", exist_ok=True)
    os.makedirs("qrcodes", exist_ok=True)
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reg_no TEXT UNIQUE,
                name TEXT,
                course TEXT,
                mobile TEXT,
                photo_path TEXT,
                qr_path TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER,
                date TEXT,
                time TEXT,
                match_percentage REAL,
                UNIQUE(student_id, date) ON CONFLICT IGNORE
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_attendance_student_date ON attendance(student_id, date)")
        conn.commit()

init_db()

# ---------- Small styled helpers ----------
def neon_entry(parent, var=None, readonly=False, width=28):
    e = tk.Entry(parent, textvariable=var, width=width,
                 bg="#101010", fg="#00ffff", insertbackground="#00ffff",
                 relief="flat", highlightthickness=1,
                 highlightbackground="#0099aa", highlightcolor="#00ffff",
                 font=("Segoe UI", 12))
    if readonly:
        e.config(state="readonly", readonlybackground="#101010")
    e.pack(pady=4, fill="x")
    return e

def neon_button(parent, text, command, bg="#0aa", fg="white"):
    b = tk.Button(parent, text=text, command=command,
                  bg=bg, fg=fg, bd=0, padx=12, pady=8,
                  activebackground="#14c4c4", activeforeground="white",
                  font=("Segoe UI", 11, "bold"))
    b.pack(pady=6, fill="x")
    return b

# ---------- Enrollment ----------
def open_enrollment():
    win = tk.Toplevel(root)
    win.title("Enrollment")
    win.configure(bg="#1e1e1e")
    win.geometry("820x540")

    # Left form
    form = tk.Frame(win, bg="#1e1e1e")
    form.pack(side="left", padx=20, pady=20, fill="y")
    tk.Label(form, text="Register Student", font=("Segoe UI", 18, "bold"), fg="white", bg="#1e1e1e").pack(pady=(0,10))

    vars_map = {}
    for label in ["Reg No", "Name", "Course", "Mobile"]:
        tk.Label(form, text=f"{label}:", fg="white", bg="#1e1e1e", font=("Segoe UI", 11)).pack(anchor="w")
        ent = tk.Entry(form, font=("Segoe UI", 13), bg="#101010", fg="white", relief="flat")
        ent.pack(fill="x", pady=5)
        vars_map[label] = ent

    # Right: live camera preview
    video_frame = tk.Frame(win, bg="#1e1e1e")
    video_frame.pack(side="right", padx=20, pady=20)
    lbl_video = tk.Label(video_frame, bg="#1e1e1e")
    lbl_video.pack()

    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAM_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAM_HEIGHT)

    def update_cam():
        ret, frame = cap.read()
        if ret:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(frame).resize((CAM_WIDTH//2, CAM_HEIGHT//2))
            imgtk = ImageTk.PhotoImage(img)
            lbl_video.imgtk = imgtk
            lbl_video.configure(image=imgtk)
        lbl_video.after(15, update_cam)
    update_cam()

    def save_student():
        reg = vars_map["Reg No"].get().strip()
        name = vars_map["Name"].get().strip()
        course = vars_map["Course"].get().strip()
        mobile = vars_map["Mobile"].get().strip()
        if not all([reg, name, course, mobile]):
            return messagebox.showerror("Error", "All fields required")

        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM students WHERE reg_no=?", (reg,))
        if cur.fetchone():
            conn.close()
            return messagebox.showerror("Error", "Student already registered")

        ok, frame = cap.read()
        if not ok:
            conn.close()
            return messagebox.showerror("Error", "Camera error")

        photo_path = os.path.join("photos", f"{reg}.jpg")
        cv2.imwrite(photo_path, frame)

        qr_path = os.path.join("qrcodes", f"{reg}.png")
        qrcode.make(reg).save(qr_path)

        cur.execute("""INSERT INTO students (reg_no, name, course, mobile, photo_path, qr_path)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (reg, name, course, mobile, photo_path, qr_path))
        conn.commit()
        conn.close()

        messagebox.showinfo("Success", f"{name} enrolled")
        for e in vars_map.values():
            e.delete(0, tk.END)

    neon_button(form, "📷 Capture & Save", save_student, bg="#4CAF50")

    def on_close():
        try: cap.release()
        except: pass
        cv2.destroyAllWindows()
        win.destroy()
    win.protocol("WM_DELETE_WINDOW", on_close)

# ---------- Attendance: fully automatic ----------
def open_attendance():
    win = tk.Toplevel(root)
    win.title("Auto Attendance")
    win.configure(bg="#0d0d0d")
    win.geometry("1050x620")

    # Left: inputs & student info
    left = tk.Frame(win, bg="#0d0d0d")
    left.pack(side="left", fill="y", padx=20, pady=20)

    tk.Label(left, text="Auto Attendance", font=("Segoe UI", 18, "bold"),
             fg="#00ffff", bg="#0d0d0d").pack(pady=(0,10))

    reg_var = tk.StringVar()
    sid_var = tk.StringVar()
    name_var = tk.StringVar()
    course_var = tk.StringVar()
    photo_var = tk.StringVar()

    tk.Label(left, text="Reg No:", bg="#0d0d0d", fg="#00ffff", font=("Segoe UI", 11)).pack(anchor="w")
    reg_entry = neon_entry(left, reg_var)
    reg_entry.focus_set()

    # row of buttons
    btn_row = tk.Frame(left, bg="#0d0d0d")
    btn_row.pack(fill="x", pady=(6,10))
    def do_fetch():
        rn = reg_var.get().strip()
        if rn:
            fetch_student(rn)
        else:
            messagebox.showerror("Error", "Enter Reg No or use Scan QR")
    neon_button(btn_row, "Fetch", do_fetch, bg="#14818f")
    neon_button(btn_row, "Scan QR", lambda: start_qr_scan(), bg="#884EA0")

    # Student info (readonly)
    tk.Label(left, text="Name:", bg="#0d0d0d", fg="white").pack(anchor="w", pady=(8,0))
    name_entry = neon_entry(left, name_var, readonly=True)

    tk.Label(left, text="Course:", bg="#0d0d0d", fg="white").pack(anchor="w", pady=(8,0))
    course_entry = neon_entry(left, course_var, readonly=True)

    tk.Label(left, text="Photo Path:", bg="#0d0d0d", fg="white").pack(anchor="w", pady=(8,0))
    photo_entry = neon_entry(left, photo_var, readonly=True)

    # Right: camera preview + live % overlay
    right = tk.Frame(win, bg="#0d0d0d")
    right.pack(side="right", fill="both", expand=True, padx=20, pady=20)

    preview_title = tk.Label(right, text="Live Camera", font=("Segoe UI", 14, "bold"),
                             fg="#00ff88", bg="#0d0d0d")
    preview_title.pack(anchor="w")

    preview_label = tk.Label(right, bg="#101010", width=CAM_WIDTH, height=CAM_HEIGHT)
    preview_label.pack(pady=10)

    status_lbl = tk.Label(right, text="Waiting for student...", fg="#b0b0b0", bg="#0d0d0d", font=("Segoe UI", 11))
    status_lbl.pack(anchor="w")

    # camera
    cam = cv2.VideoCapture(0)
    cam.set(cv2.CAP_PROP_FRAME_WIDTH, CAM_WIDTH)
    cam.set(cv2.CAP_PROP_FRAME_HEIGHT, CAM_HEIGHT)

    # runtime state
    stored_encoding = [None]  # list to allow closure assignment
    running_match = [False]
    consecutive = [0]

    def fetch_student(regno):
        # load details
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT id, name, course, photo_path FROM students WHERE reg_no=?", (regno,))
        rec = cur.fetchone()
        conn.close()

        if not rec:
            status_lbl.config(text="Student not found.")
            name_var.set(""); course_var.set(""); photo_var.set(""); sid_var.set("")
            return

        sid_var.set(str(rec[0]))
        name_var.set(rec[1] or "")
        course_var.set(rec[2] or "")
        photo_var.set(rec[3] or "")

        # get face encoding from stored photo
        path = photo_var.get()
        if not path or not os.path.exists(path):
            status_lbl.config(text="Stored photo not found.")
            return
        try:
            img = face_recognition.load_image_file(path)
            encs = face_recognition.face_encodings(img)
            if not encs:
                status_lbl.config(text="No face in stored photo.")
                return
            stored_encoding[0] = encs[0]
            status_lbl.config(text="Student loaded. Starting live recognition...")
            start_recognition()
        except Exception as e:
            stored_encoding[0] = None
            status_lbl.config(text=f"Error loading face: {e}")

    def start_qr_scan():
        # Use the same camera; read frames and decode
        status_lbl.config(text="Scanning QR... (hold code in front of camera)")
        def scan_loop():
            ret, frame = cam.read()
            if ret:
                # draw and show
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                codes = decode(rgb)
                if codes:
                    # take first text
                    data = codes[0].data.decode("utf-8").strip()
                    reg_var.set(data)
                    status_lbl.config(text=f"QR: {data}")
                    fetch_student(data)
                    return  # stop scanning, we’ll switch to recognition
            preview_label.after(30, scan_loop)
        scan_loop()

    def start_recognition():
        if stored_encoding[0] is None or not sid_var.get():
            return
        running_match[0] = True
        consecutive[0] = 0
        loop_frame()

    def loop_frame():
        # Unified preview loop for either waiting, QR, or recognition
        ret, frame = cam.read()
        if not ret:
            status_lbl.config(text="Camera not available.")
            return preview_label.after(150, loop_frame)

        display = frame.copy()
        msg = "Ready"
        color = (0, 255, 255)

        if stored_encoding[0] is not None and running_match[0]:
            # recognition mode
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            encs = face_recognition.face_encodings(rgb)
            if encs:
                dist = face_recognition.face_distance([stored_encoding[0]], encs[0])[0]
                pct = (1.0 - max(0.0, min(1.0, float(dist)))) * 100.0
                is_match = dist <= TOLERANCE
                msg = f"Match: {pct:.2f}%"
                color = (0, 255, 0) if is_match else (0, 0, 255)
                cv2.putText(display, msg, (16, 36), cv2.FONT_HERSHEY_SIMPLEX, 1, color, 2)
                cv2.putText(display, "MATCH" if is_match else "NO MATCH", (16, 72),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2)
                if is_match:
                    consecutive[0] += 1
                else:
                    consecutive[0] = max(0, consecutive[0]-1)

                if consecutive[0] >= REQ_CONSEC:
                    # save attendance and stop matching for now
                    now = datetime.now()
                    with get_conn() as conn2:
                        cur2 = conn2.cursor()
                        cur2.execute("""INSERT OR IGNORE INTO attendance
                                        (student_id, date, time, match_percentage)
                                        VALUES (?, ?, ?, ?)""",
                                     (sid_var.get(), now.strftime("%Y-%m-%d"),
                                      now.strftime("%H:%M:%S"), float(pct)))
                        conn2.commit()
                    running_match[0] = False
                    status_lbl.config(text=f"Attendance saved: {name_var.get()} ({pct:.2f}%)")
                    # reset enc so we can scan next student
                    stored_encoding[0] = None
                    # keep camera running, waiting for next reg or QR
            else:
                msg = "Looking for face..."
                color = (255, 255, 0)

        # draw instruction
        cv2.rectangle(display, (10, 10), (CAM_WIDTH-10, CAM_HEIGHT-10), color, 2)

        # update tkinter image
        rgb_disp = cv2.cvtColor(display, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(rgb_disp).resize((CAM_WIDTH, CAM_HEIGHT))
        imgtk = ImageTk.PhotoImage(img)
        preview_label.imgtk = imgtk
        preview_label.configure(image=imgtk)

        preview_label.after(15, loop_frame)

    # Enter on reg field triggers fetch + auto recognition
    def on_enter_reg(event=None):
        rn = reg_var.get().strip()
        if rn:
            fetch_student(rn)
    reg_entry.bind("<Return>", on_enter_reg)

    # kick camera loop
    loop_frame()

    def on_close():
        try: cam.release()
        except: pass
        cv2.destroyAllWindows()
        win.destroy()
    win.protocol("WM_DELETE_WINDOW", on_close)

# ---------- Reports (filters + search + export) ----------
def open_reports():
    win = tk.Toplevel(root)
    win.title("Attendance Reports")
    win.geometry("1000x620")
    win.configure(bg="#1e1e1e")

    date_var = tk.StringVar()
    search_var = tk.StringVar()

    def load_dataframe(date_filter=None, search_filter=None):
        if not os.path.exists(DB_FILE): return pd.DataFrame()
        conn = get_conn()
        base = """
            SELECT s.reg_no AS "Reg No",
                   s.name   AS "Name",
                   s.course AS "Course",
                   a.date   AS "Date",
                   a.time   AS "Time",
                   a.match_percentage AS "Match %"
            FROM attendance a
            JOIN students s ON a.student_id = s.id
        """
        conds, params = [], []
        if date_filter:
            conds.append("a.date = ?"); params.append(date_filter)
        if search_filter:
            conds.append("(s.reg_no LIKE ? OR s.name LIKE ?)")
            q = f"%{search_filter}%"; params.extend([q, q])
        if conds: base += " WHERE " + " AND ".join(conds)
        base += " ORDER BY a.date DESC, a.time DESC"
        df = pd.read_sql_query(base, conn, params=params); conn.close()
        return df

    def update_table():
        for r in tree.get_children(): tree.delete(r)
        df = load_dataframe(date_var.get().strip() or None, search_var.get().strip() or None)
        for _, row in df.iterrows():
            tree.insert("", tk.END, values=(row["Reg No"], row["Name"], row["Course"],
                                            row["Date"], row["Time"],
                                            f"{float(row['Match %']):.2f}%"))

    def export_data():
        df = load_dataframe(date_var.get().strip() or None, search_var.get().strip() or None)
        if df.empty:
            return messagebox.showwarning("No Data", "Nothing to export.")
        path = filedialog.asksaveasfilename(defaultextension=".xlsx",
                                            filetypes=[("Excel", "*.xlsx"), ("CSV", "*.csv")])
        if not path: return
        try:
            if path.lower().endswith(".csv"): df.to_csv(path, index=False)
            else: df.to_excel(path, index=False)
            messagebox.showinfo("Exported", f"Saved: {path}")
        except Exception as e:
            messagebox.showerror("Export Error", str(e))

    def refresh_dates_dropdown():
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT DISTINCT date FROM attendance ORDER BY date DESC LIMIT 100")
        rows = [r[0] for r in cur.fetchall()]
        conn.close()
        date_combo["values"] = [""] + rows

    # Top controls
    top = tk.Frame(win, bg="#1e1e1e")
    top.pack(fill="x", padx=12, pady=10)
    tk.Label(top, text="Date:", fg="white", bg="#1e1e1e").pack(side="left")
    date_combo = ttk.Combobox(top, textvariable=date_var, width=16)
    date_combo.pack(side="left", padx=6)
    tk.Label(top, text="Search:", fg="white", bg="#1e1e1e").pack(side="left", padx=(8,4))
    tk.Entry(top, textvariable=search_var, width=26).pack(side="left")
    tk.Button(top, text="Load", command=update_table, bg="#4CAF50", fg="white").pack(side="left", padx=8)
    tk.Button(top, text="Refresh Dates", command=refresh_dates_dropdown, bg="#777", fg="white").pack(side="left", padx=6)
    tk.Button(top, text="Export", command=export_data, bg="#2196F3", fg="white").pack(side="left", padx=6)

    # Table
    cols = ("Reg No","Name","Course","Date","Time","Match %")
    style = ttk.Style()
    try:
        style.theme_use('clam')
    except:
        pass
    style.configure("Treeview",
                    background="#2b2b2b", foreground="white",
                    fieldbackground="#2b2b2b", rowheight=26, borderwidth=0)
    style.configure("Treeview.Heading",
                    background="#1f1f1f", foreground="white",
                    font=("Segoe UI", 11, "bold"))
    style.map("Treeview", background=[("selected","#4CAF50")])

    table_frame = tk.Frame(win, bg="#1e1e1e")
    table_frame.pack(fill="both", expand=True, padx=12, pady=(0,12))
    tree = ttk.Treeview(table_frame, columns=cols, show="headings")
    for c in cols:
        tree.heading(c, text=c)
        tree.column(c, anchor=tk.CENTER, width=140)
    vsb = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=vsb.set)
    vsb.pack(side="right", fill="y")
    tree.pack(fill="both", expand=True)

    refresh_dates_dropdown()
    update_table()

# ---------- Tools (styled + extra utilities) ----------
def open_tools_window():
    win = tk.Toplevel(root)
    win.title("Tools")
    win.geometry("820x580")
    win.configure(bg="#161616")

    # QR generator
    frm_qr = tk.LabelFrame(win, text="QR Code Generator", bg="#161616", fg="white", padx=10, pady=10)
    frm_qr.pack(fill="x", padx=12, pady=(12,6))
    tk.Label(frm_qr, text="Reg No:", bg="#161616", fg="white").grid(row=0, column=0, sticky="w")
    qr_reg = tk.StringVar()
    tk.Entry(frm_qr, textvariable=qr_reg, width=24, bg="#101010", fg="white", relief="flat").grid(row=0, column=1, padx=8)
    def gen_qr():
        r = qr_reg.get().strip()
        if not r: return
        os.makedirs("qrcodes", exist_ok=True)
        path = os.path.join("qrcodes", f"{r}.png")
        qrcode.make(r).save(path)
        messagebox.showinfo("QR", f"Saved: {path}")
    tk.Button(frm_qr, text="Generate", command=gen_qr, bg="#4CAF50", fg="white").grid(row=0, column=2, padx=8)

    # DB backup/restore
    frm_db = tk.LabelFrame(win, text="Database Backup / Restore", bg="#161616", fg="white", padx=10, pady=10)
    frm_db.pack(fill="x", padx=12, pady=6)
    def backup_db():
        if not os.path.exists(DB_FILE): return messagebox.showerror("Error","DB not found")
        dest = filedialog.asksaveasfilename(defaultextension=".db", filetypes=[("SQLite DB","*.db")])
        if not dest: return
        shutil.copy2(DB_FILE, dest)
        messagebox.showinfo("Backup", f"Saved to: {dest}")
    def restore_db():
        src = filedialog.askopenfilename(filetypes=[("SQLite DB","*.db"),("All files","*.*")])
        if not src: return
        if not messagebox.askyesno("Confirm","Overwrite current DB?"): return
        shutil.copy2(src, DB_FILE)
        messagebox.showinfo("Restore","Database restored.")
    tk.Button(frm_db, text="Backup", command=backup_db, bg="#2196F3", fg="white").pack(side="left", padx=8)
    tk.Button(frm_db, text="Restore", command=restore_db, bg="#f39c12", fg="white").pack(side="left", padx=8)

    # Export students
    frm_students = tk.LabelFrame(win, text="Export Student List", bg="#161616", fg="white", padx=10, pady=10)
    frm_students.pack(fill="x", padx=12, pady=6)
    def export_students():
        conn = get_conn()
        df = pd.read_sql_query("""SELECT reg_no AS "Reg No", name AS "Name",
                                         course AS "Course", mobile AS "Mobile"
                                  FROM students ORDER BY reg_no""", conn)
        conn.close()
        if df.empty: return messagebox.showinfo("No Data","No students.")
        path = filedialog.asksaveasfilename(defaultextension=".xlsx",
                                            filetypes=[("Excel","*.xlsx"),("CSV","*.csv")])
        if not path: return
        if path.lower().endswith(".csv"): df.to_csv(path, index=False)
        else: df.to_excel(path, index=False)
        messagebox.showinfo("Exported", f"Saved: {path}")
    tk.Button(frm_students, text="Export Students", command=export_students,
              bg="#8e44ad", fg="white").pack(side="left", padx=8)

    # Attendance Summary
    frm_sum = tk.LabelFrame(win, text="Attendance Summary (Per Day)", bg="#161616", fg="white", padx=10, pady=10)
    frm_sum.pack(fill="both", expand=True, padx=12, pady=(6,12))
    sum_cols = ("Date","Present Count")
    tree_sum = ttk.Treeview(frm_sum, columns=sum_cols, show="headings", height=9)
    for c in sum_cols:
        tree_sum.heading(c, text=c)
        tree_sum.column(c, anchor=tk.CENTER, width=160)
    tree_sum.pack(side="left", fill="both", expand=True)
    vsb2 = ttk.Scrollbar(frm_sum, orient="vertical", command=tree_sum.yview)
    tree_sum.configure(yscrollcommand=vsb2.set)
    vsb2.pack(side="left", fill="y", padx=6)

    def load_summary():
        for r in tree_sum.get_children(): tree_sum.delete(r)
        conn = get_conn()
        df = pd.read_sql_query("""SELECT date AS "Date", COUNT(*) AS "Present Count"
                                  FROM attendance GROUP BY date ORDER BY date DESC""", conn)
        conn.close()
        for _, row in df.iterrows():
            tree_sum.insert("", tk.END, values=(row["Date"], int(row["Present Count"])))
    def export_summary():
        conn = get_conn()
        df = pd.read_sql_query("""SELECT date AS "Date", COUNT(*) AS "Present Count"
                                  FROM attendance GROUP BY date ORDER BY date DESC""", conn)
        conn.close()
        if df.empty: return messagebox.showinfo("No Data","Nothing to export.")
        path = filedialog.asksaveasfilename(defaultextension=".xlsx",
                                            filetypes=[("Excel","*.xlsx"),("CSV","*.csv")])
        if not path: return
        if path.lower().endswith(".csv"): df.to_csv(path, index=False)
        else: df.to_excel(path, index=False)
        messagebox.showinfo("Exported", f"Saved: {path}")

    btns = tk.Frame(frm_sum, bg="#161616")
    btns.pack(side="left", fill="y", padx=10)
    tk.Button(btns, text="Load Summary", command=load_summary, bg="#16a085", fg="white").pack(pady=6, fill="x")
    tk.Button(btns, text="Export Summary", command=export_summary, bg="#2980b9", fg="white").pack(pady=6, fill="x")

    load_summary()

# ---------- Dashboard ----------
root = tk.Tk()
root.title(APP_TITLE)
try:
    root.state("zoomed")
except:
    root.attributes("-fullscreen", True)
root.configure(bg="#121212")

# top bar
top = tk.Frame(root, bg="#121212", pady=12)
top.pack(fill="x")
if os.path.exists(LOGO_FILE):
    try:
        l = Image.open(LOGO_FILE).resize((86,86))
        logo_img = ImageTk.PhotoImage(l)
        tk.Label(top, image=logo_img, bg="#121212").pack(side="left", padx=20)
    except:
        tk.Label(top, text="", bg="#121212").pack(side="left", padx=20)
else:
    tk.Label(top, text="", bg="#121212").pack(side="left", padx=20)

tk.Label(top, text="Central University of Andhra Pradesh",
         font=("Helvetica", 28, "bold"), fg="white", bg="#121212").pack(side="left")
tk.Label(top, text=DEVELOPER_TEXT, fg="#B0B0B0", bg="#121212", font=("Segoe UI", 11)).pack(side="right", padx=20)

# card grid
center = tk.Frame(root, bg="#121212"); center.pack(expand=True)

CARD_BG, HOVER_BG = "#1f1f1f", "#2e7d32"
def make_card(parent, icon_text, label_text, command):
    card = tk.Frame(parent, bg=CARD_BG, width=260, height=160)
    card.pack_propagate(False)
    icon = tk.Label(card, text=icon_text, font=("Segoe UI Emoji", 28), bg=CARD_BG, fg="white")
    icon.pack(pady=(12,2))
    lbl = tk.Label(card, text=label_text, font=("Segoe UI", 14, "bold"), bg=CARD_BG, fg="white")
    lbl.pack()
    def on_enter(e): 
        card.configure(bg=HOVER_BG); icon.configure(bg=HOVER_BG); lbl.configure(bg=HOVER_BG)
    def on_leave(e): 
        card.configure(bg=CARD_BG); icon.configure(bg=CARD_BG); lbl.configure(bg=CARD_BG)
    for w in (card, icon, lbl):
        w.bind("<Enter>", on_enter); w.bind("<Leave>", on_leave); w.bind("<Button-1>", lambda e: command())
    return card

grid = tk.Frame(center, bg="#121212"); grid.pack()
make_card(grid, "📝", "Enroll Student", open_enrollment).grid(row=0, column=0, padx=24, pady=18)
make_card(grid, "📷", "Auto Attendance", open_attendance).grid(row=0, column=1, padx=24, pady=18)
make_card(grid, "📊", "Reports", open_reports).grid(row=1, column=0, padx=24, pady=18)
make_card(grid, "🛠", "Tools", open_tools_window).grid(row=1, column=1, padx=24, pady=18)

# bottom bar
bottom = tk.Frame(root, bg="#121212", pady=10); bottom.pack(fill="x", side="bottom")
def exit_app():
    if messagebox.askyesno("Exit", "Close the dashboard?"):
        root.destroy()
tk.Label(bottom, text=DEVELOPER_TEXT, fg="#B0B0B0", bg="#121212", font=("Segoe UI", 11)).pack(side="left", padx=20)
tk.Button(bottom, text="Exit", command=exit_app, bg="#d32f2f", fg="white").pack(side="right", padx=18)

# shortcuts
root.bind("<Escape>", lambda e: exit_app())
root.bind("e", lambda e: open_enrollment())
root.bind("a", lambda e: open_attendance())
root.bind("r", lambda e: open_reports())
root.bind("t", lambda e: open_tools_window())

root.mainloop()
