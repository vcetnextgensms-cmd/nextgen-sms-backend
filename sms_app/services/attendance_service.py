from datetime import datetime, timedelta, timezone

from database import audit, connect

VALID_SESSION_TYPES = ("CLASS", "LAB")
VALID_CLASS_HOURS = (1, 2, 3)
LAB_HOURS = 3


def validate_session_payload(*, attendance_date, semester_id, subject_id, faculty_username,
                             session_type, duration_hours, topic):
    try:
        datetime.strptime(attendance_date, "%Y-%m-%d")
    except (TypeError, ValueError):
        raise ValueError("Select a valid attendance date")
    if not semester_id:
        raise ValueError("Select a semester")
    if not subject_id:
        raise ValueError("Select a subject")
    if not faculty_username:
        raise ValueError("A faculty account is required")
    session_type = str(session_type or "").upper()
    if session_type not in VALID_SESSION_TYPES:
        raise ValueError("Choose Class or Lab")
    try:
        duration_hours = int(duration_hours)
    except (TypeError, ValueError):
        raise ValueError("Choose the session duration")
    if session_type == "LAB":
        duration_hours = LAB_HOURS
    elif session_type == "CLASS" and duration_hours not in VALID_CLASS_HOURS:
        raise ValueError("Class duration must be 1, 2, or 3 hours")
    topic = str(topic or "").strip()
    if not topic:
        raise ValueError("Enter today's topic")
    if len(topic) > 300:
        raise ValueError("Today's topic must be 300 characters or fewer")
    return session_type, duration_hours, topic


def list_semesters():
    with connect() as c:
        return c.execute("SELECT id, code, name FROM academic_semesters ORDER BY sort_order").fetchall()


def list_all_semesters():
    """HOD-facing semester management view: every semester, active AND
    inactive, so HOD can see and toggle 1st Year (or any other semester)
    on/off. Unlike list_semesters() (used everywhere else — subject
    pickers, faculty attendance workflow, etc.) which only returns active
    ones, so a deactivated semester disappears from normal use immediately.
    """
    with connect() as c:
        return c.execute("SELECT id, code, name, sort_order, active FROM academic_semesters ORDER BY sort_order").fetchall()


def set_semester_active(*, semester_id, active, actor):
    with connect() as c:
        row = c.execute("SELECT * FROM academic_semesters WHERE id=%s", (semester_id,)).fetchone()
        if not row:
            raise ValueError("Semester was not found")
        c.execute("UPDATE academic_semesters SET active=%s WHERE id=%s", (1 if active else 0, semester_id))
        audit(c, actor, "STATUS", "semester", f"{row['code']} -> {'active' if active else 'inactive'}")


def faculty_semester_ids(faculty_username):
    """Semester ids a given faculty member teaches in (derived from their
    subject assignments), used to scope Academic Calendar to only the
    semesters that faculty member is relevant to.
    """
    with connect() as c:
        rows = c.execute("""
            SELECT DISTINCT s.semester_id
            FROM subjects s JOIN subject_faculty sf ON sf.subject_id = s.id
            WHERE sf.faculty_username = %s AND s.active = 1
        """, (faculty_username,)).fetchall()
        return [r["semester_id"] for r in rows]


def academic_calendar_for_semesters(semester_ids=None):
    """Semester + Timetable/Calendar upload info, joined, ordered by
    sort_order. semester_ids=None returns every active semester (HOD view);
    a list scopes to just those semesters (Faculty/Student views).
    """
    with connect() as c:
        sql = """
            SELECT sem.id AS semester_id, sem.code, sem.name, sem.sort_order,
                   ac.timetable_path, ac.timetable_updated_at, ac.timetable_updated_by,
                   ac.calendar_path, ac.calendar_updated_at, ac.calendar_updated_by
            FROM academic_semesters sem
            LEFT JOIN academic_calendar ac ON ac.semester_id = sem.id
            WHERE sem.active = 1
        """
        args = []
        if semester_ids is not None:
            if not semester_ids:
                return []
            placeholders = ",".join("%s" for _ in semester_ids)
            sql += f" AND sem.id IN ({placeholders})"
            args = list(semester_ids)
        sql += " ORDER BY sem.sort_order"
        return c.execute(sql, args).fetchall()


def save_calendar_upload(*, semester_id, kind, path, actor):
    """kind: 'timetable' or 'calendar'. Upserts the academic_calendar row
    for this semester — HOD-only write path (enforced at the route level).
    """
    if kind not in ("timetable", "calendar"):
        raise ValueError("Invalid upload kind")
    path_col = f"{kind}_path"
    at_col = f"{kind}_updated_at"
    by_col = f"{kind}_updated_by"
    with connect() as c:
        sem = c.execute("SELECT code FROM academic_semesters WHERE id=%s", (semester_id,)).fetchone()
        if not sem:
            raise ValueError("Semester was not found")
        c.execute(f"""
            INSERT INTO academic_calendar(semester_id, {path_col}, {at_col}, {by_col})
            VALUES(%s, %s, CURRENT_TIMESTAMP, %s)
            ON DUPLICATE KEY UPDATE
                {path_col}=VALUES({path_col}), {at_col}=CURRENT_TIMESTAMP, {by_col}=VALUES({by_col})
        """, (semester_id, path, actor))
        audit(c, actor, "UPLOAD", "academic_calendar", f"{sem['code']} ({kind})")


def delete_calendar_upload(*, semester_id, kind, actor):
    """kind: 'timetable' or 'calendar'. Clears the path for this semester."""
    if kind not in ("timetable", "calendar"):
        raise ValueError("Invalid upload kind")
    path_col = f"{kind}_path"
    at_col = f"{kind}_updated_at"
    by_col = f"{kind}_updated_by"
    with connect() as c:
        sem = c.execute("SELECT code FROM academic_semesters WHERE id=%s", (semester_id,)).fetchone()
        if not sem:
            raise ValueError("Semester was not found")
        c.execute(f"""
            UPDATE academic_calendar SET {path_col}=NULL, {at_col}=CURRENT_TIMESTAMP, {by_col}=%s
            WHERE semester_id=%s
        """, (actor, semester_id))
        audit(c, actor, "DELETE_UPLOAD", "academic_calendar", f"{sem['code']} ({kind})")


def list_subjects(semester_id, username=None, role=None):
    with connect() as c:
        if role == "FACULTY":
            rows = c.execute("""
                SELECT s.id,s.code,s.name,s.has_lab
                FROM subjects s
                JOIN subject_faculty sf ON sf.subject_id=s.id
                WHERE s.semester_id=%s AND s.active=1 AND sf.faculty_username=%s
                ORDER BY s.name
            """, (semester_id, username)).fetchall()
            if rows:
                return rows
        return c.execute("SELECT id,code,name,has_lab FROM subjects WHERE semester_id=%s AND active=1 ORDER BY name", (semester_id,)).fetchall()


def subject_faculty_map():
    """Subject -> assigned faculty, grouped by semester. Inverse of
    faculty_teaching_hours() (which is faculty -> aggregate hours); this is
    the "which faculty teaches this subject" view Boss asked for
    (HANDOFF.md Session 3, item 5). Uses only existing tables/columns —
    no schema change needed.
    """
    with connect() as c:
        rows = c.execute("""
            SELECT sem.id AS semester_id, sem.code AS semester_code, sem.name AS semester_name,
                   s.id AS subject_id, s.code AS subject_code, s.name AS subject_name, s.has_lab,
                   sf.faculty_username, u.full_name AS faculty_full_name
            FROM subjects s
            JOIN academic_semesters sem ON sem.id = s.semester_id
            LEFT JOIN subject_faculty sf ON sf.subject_id = s.id
            LEFT JOIN users u ON u.username = sf.faculty_username
            WHERE s.active = 1
            ORDER BY sem.sort_order, s.name, u.full_name
        """).fetchall()

    semesters: dict[int, dict] = {}
    for r in rows:
        sem = semesters.setdefault(r["semester_id"], {
            "semester_id": r["semester_id"], "semester_code": r["semester_code"],
            "semester_name": r["semester_name"], "subjects": {},
        })
        subj = sem["subjects"].setdefault(r["subject_id"], {
            "subject_id": r["subject_id"], "subject_code": r["subject_code"],
            "subject_name": r["subject_name"], "has_lab": r["has_lab"], "faculty": [],
        })
        if r["faculty_username"]:
            subj["faculty"].append(r["faculty_full_name"] or r["faculty_username"])

    return [
        {**sem, "subjects": list(sem["subjects"].values())}
        for sem in semesters.values()
    ]


def subject_details(subject_id):
    with connect() as c:
        return c.execute("""
            SELECT s.*, sem.code AS semester_code, sem.name AS semester_name
            FROM subjects s JOIN academic_semesters sem ON sem.id=s.semester_id
            WHERE s.id=%s
        """, (subject_id,)).fetchone()


def validate_subject_payload(*, code, name, has_lab):
    code = str(code or "").strip().upper()
    name = str(name or "").strip()
    if not code:
        raise ValueError("Subject code is required")
    if not name:
        raise ValueError("Subject name is required")
    return code, name, 1 if has_lab else 0


def all_subjects_admin():
    """HOD-facing subject management view: every subject (active AND
    inactive, unlike subject_faculty_map()/list_subjects() which only
    show active ones), grouped by semester, with the list of assigned
    faculty usernames so the assignment form can pre-check them.
    """
    with connect() as c:
        semesters = c.execute(
            "SELECT id, code, name FROM academic_semesters WHERE active=1 ORDER BY sort_order"
        ).fetchall()
        subjects = c.execute("""
            SELECT s.id, s.semester_id, s.code, s.name, s.has_lab, s.active
            FROM subjects s ORDER BY s.semester_id, s.name
        """).fetchall()
        assigned = c.execute("""
            SELECT sf.subject_id, sf.faculty_username, u.full_name
            FROM subject_faculty sf JOIN users u ON u.username = sf.faculty_username
        """).fetchall()

    by_subject: dict[int, list[dict]] = {}
    for r in assigned:
        by_subject.setdefault(r["subject_id"], []).append(
            {"username": r["faculty_username"], "full_name": r["full_name"] or r["faculty_username"]}
        )

    subjects_by_sem: dict[int, list[dict]] = {}
    for s in subjects:
        subjects_by_sem.setdefault(s["semester_id"], []).append({
            "id": s["id"], "code": s["code"], "name": s["name"],
            "has_lab": s["has_lab"], "active": s["active"],
            "faculty": by_subject.get(s["id"], []),
        })

    return [
        {"id": sem["id"], "code": sem["code"], "name": sem["name"],
         "subjects": subjects_by_sem.get(sem["id"], [])}
        for sem in semesters
    ]


def create_subject(*, semester_id, code, name, has_lab, actor):
    code, name, has_lab = validate_subject_payload(code=code, name=name, has_lab=has_lab)
    with connect() as c:
        if not c.execute("SELECT 1 FROM academic_semesters WHERE id=%s", (semester_id,)).fetchone():
            raise ValueError("Select a valid semester")
        cur = c.execute(
            "INSERT INTO subjects(semester_id,code,name,has_lab) VALUES(%s,%s,%s,%s)",
            (semester_id, code, name, has_lab),
        )
        audit(c, actor, "CREATE", "subject", f"{code} - {name} (semester={semester_id})")
        return cur.lastrowid


def update_subject(*, subject_id, code, name, has_lab, actor):
    code, name, has_lab = validate_subject_payload(code=code, name=name, has_lab=has_lab)
    with connect() as c:
        row = c.execute("SELECT * FROM subjects WHERE id=%s", (subject_id,)).fetchone()
        if not row:
            raise ValueError("Subject was not found")
        c.execute("UPDATE subjects SET code=%s, name=%s, has_lab=%s WHERE id=%s", (code, name, has_lab, subject_id))
        audit(c, actor, "UPDATE", "subject", f"{subject_id}: {row['code']} - {row['name']} -> {code} - {name}")


def set_subject_active(*, subject_id, active, actor):
    with connect() as c:
        row = c.execute("SELECT * FROM subjects WHERE id=%s", (subject_id,)).fetchone()
        if not row:
            raise ValueError("Subject was not found")
        c.execute("UPDATE subjects SET active=%s WHERE id=%s", (1 if active else 0, subject_id))
        audit(c, actor, "STATUS", "subject", f"{row['code']} -> {'active' if active else 'inactive'}")


def delete_subject(*, subject_id, actor):
    with connect() as c:
        row = c.execute("SELECT * FROM subjects WHERE id=%s", (subject_id,)).fetchone()
        if not row:
            raise ValueError("Subject was not found")
        sess = c.execute("SELECT COUNT(*) AS cnt FROM attendance_sessions WHERE subject_id=%s", (subject_id,)).fetchone()
        if sess and sess["cnt"] > 0:
            raise ValueError("Cannot delete subject with existing attendance sessions. Please deactivate it instead.")
        c.execute("DELETE FROM subjects WHERE id=%s", (subject_id,))
        audit(c, actor, "DELETE", "subject", f"Deleted subject {row['code']} - {row['name']}")



def set_subject_faculty(*, subject_id, faculty_usernames, actor):
    """Replaces the full assigned-faculty set for a subject with
    faculty_usernames (a list of active FACULTY usernames). Editable by
    HOD any time — each subject can be given its own distinct faculty.
    """
    with connect() as c:
        subject = c.execute("SELECT * FROM subjects WHERE id=%s", (subject_id,)).fetchone()
        if not subject:
            raise ValueError("Subject was not found")
        valid = {
            r["username"] for r in c.execute(
                "SELECT username FROM users WHERE role='FACULTY' AND active=1"
            ).fetchall()
        }
        chosen = [u for u in dict.fromkeys(faculty_usernames or []) if u in valid]
        c.execute("DELETE FROM subject_faculty WHERE subject_id=%s", (subject_id,))
        for username in chosen:
            c.execute("INSERT INTO subject_faculty(subject_id,faculty_username) VALUES(%s,%s)", (subject_id, username))
        audit(c, actor, "UPDATE", "subject_faculty",
              f"{subject['code']}: faculty=[{', '.join(chosen) or '—'}]")


def get_or_create_session(*, attendance_date, semester_id, subject_id, faculty_username,
                          session_type, duration_hours, topic, actor):
    session_type, duration_hours, topic = validate_session_payload(
        attendance_date=attendance_date, semester_id=semester_id, subject_id=subject_id,
        faculty_username=faculty_username, session_type=session_type,
        duration_hours=duration_hours, topic=topic,
    )
    with connect() as c:
        row = c.execute("""
            SELECT * FROM attendance_sessions
            WHERE attendance_date=%s AND subject_id=%s AND faculty_username=%s AND session_type=%s
        """, (attendance_date, subject_id, faculty_username, session_type)).fetchone()
        if row:
            return row
        cur = c.execute("""
            INSERT INTO attendance_sessions(
                attendance_date,semester_id,subject_id,faculty_username,
                session_type,duration_hours,topic,created_by
            ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
        """, (attendance_date, semester_id, subject_id, faculty_username,
              session_type, duration_hours, topic, actor))
        audit(c, actor, "CREATE", "attendance_session",
              f"session={cur.lastrowid}; subject={subject_id}; type={session_type}; hours={duration_hours}")
        return c.execute("SELECT * FROM attendance_sessions WHERE id=%s", (cur.lastrowid,)).fetchone()


def session_details(session_id):
    with connect() as c:
        return c.execute("""
            SELECT a.*, s.code AS subject_code, s.name AS subject_name,
                   sem.code AS semester_code, sem.name AS semester_name,
                   u.full_name AS faculty_name
            FROM attendance_sessions a
            JOIN subjects s ON s.id=a.subject_id
            JOIN academic_semesters sem ON sem.id=a.semester_id
            LEFT JOIN users u ON u.username=a.faculty_username
            WHERE a.id=%s
        """, (session_id,)).fetchone()


def session_is_editable(session, role):
    if role in ("HOD", "ADMIN"):
        return True
    # — UTC-consistent comparison
    # WHY: SQLite's CURRENT_TIMESTAMP (what created_at is stored with) is
    # always UTC, but formatted as a plain "YYYY-MM-DD HH:MM:SS" string
    # with no "Z" or offset — so the old .replace("Z","+00:00") was a
    # no-op here, and fromisoformat() produced a NAIVE datetime that is
    # secretly UTC-valued. Comparing that against datetime.now() (naive
    # LOCAL time) silently mixes timezones: on any server whose local
    # time is ahead of UTC (e.g. IST, UTC+5:30), the 24h edit window
    # appears to expire that many hours early, locking faculty out of
    # legitimate same-day corrections. Fix: treat created_at as UTC
    # explicitly and compare against utcnow(), both timezone-aware.
    created = datetime.fromisoformat(str(session["created_at"]).replace("Z", "")).replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    return now <= created + timedelta(hours=24)


def load_register(session_id):
    with connect() as c:
        students = c.execute("SELECT roll_no,name FROM students WHERE department='CSD' AND active=1 ORDER BY roll_no").fetchall()
        existing = {r["roll_no"]: r["status"] for r in c.execute(
            "SELECT roll_no,status FROM attendance_records WHERE session_id=%s", (session_id,)
        ).fetchall()}
    return students, existing


def sessions_last_n_days(days=15, on_date=None, semester_id=None, year=None):
    # — HOD 15-day view (P0-P1 req 5): sessions grouped by date, newest first.
    # on_date (YYYY-MM-DD): if given, shows just that single day instead of
    # the rolling N-day window (Boss's date-picker request, 2026-07-22).
    # semester_id: if given, filters sessions for that specific semester.
    # year: "1", "2", "3", or "4" — filters by academic year prefix in
    # semester code (e.g. year="2" matches codes starting with "II-").
    YEAR_PREFIXES = {"1": "I-", "2": "II-", "3": "III-", "4": "IV-"}
    with connect() as c:
        where_clauses = []
        params = []
        if on_date:
            where_clauses.append("a.attendance_date = %s")
            params.append(on_date)
        else:
            cutoff = (datetime.now().date() - timedelta(days=int(days) - 1)).isoformat()
            where_clauses.append("a.attendance_date >= %s")
            params.append(cutoff)

        if semester_id is not None:
            where_clauses.append("a.semester_id = %s")
            params.append(int(semester_id))
        elif year and year in YEAR_PREFIXES:
            prefix = YEAR_PREFIXES[year]
            where_clauses.append("sem.code LIKE %s")
            params.append(prefix + "%")

        where_clause = "WHERE " + " AND ".join(where_clauses)
        rows = c.execute(f"""
            SELECT a.id, a.attendance_date, a.session_type, a.duration_hours, a.topic, a.created_at,
                   s.name AS subject_name, s.code AS subject_code,
                   u.full_name AS faculty_name, a.faculty_username,
                   sem.code AS semester_code, sem.name AS semester_name,
                   (SELECT COUNT(*) FROM attendance_records r WHERE r.session_id=a.id AND r.status='Absent') AS absent_count,
                   (SELECT COUNT(*) FROM attendance_records r WHERE r.session_id=a.id AND r.status='Present') AS present_count,
                   (SELECT COUNT(*) FROM attendance_records r WHERE r.session_id=a.id) AS total_marked
            FROM attendance_sessions a
            JOIN subjects s ON s.id=a.subject_id
            JOIN academic_semesters sem ON sem.id=a.semester_id
            LEFT JOIN users u ON u.username=a.faculty_username
            {where_clause}
            ORDER BY a.attendance_date DESC, a.created_at DESC
        """, params).fetchall()
    grouped = {}
    for r in rows:
        grouped.setdefault(r["attendance_date"], []).append(r)
    return grouped


def absent_students_for_session(session_id):
    # — kept for internal/audit use; HOD-facing drill-down now shows Present
    # (see present_students_for_session) since a full roster is usually
    # present and the absent few are the noise-heavy case to scan, not the
    # useful one — Boss asked the button/list to reflect who showed up.
    with connect() as c:
        return c.execute("""
            SELECT st.roll_no, st.name
            FROM attendance_records r
            JOIN students st ON st.roll_no = r.roll_no
            WHERE r.session_id=%s AND r.status='Absent'
            ORDER BY st.roll_no
        """, (session_id,)).fetchall()


def present_students_for_session(session_id):
    # — P0-P1 req 5, flipped per Boss's request: click present count -> list
    # of students who attended, not who didn't.
    with connect() as c:
        return c.execute("""
            SELECT st.roll_no, st.name
            FROM attendance_records r
            JOIN students st ON st.roll_no = r.roll_no
            WHERE r.session_id=%s AND r.status='Present'
            ORDER BY st.roll_no
        """, (session_id,)).fetchall()


def student_subject_attendance(roll_no):
    # — P2 req 8/9: subject-wise % per student, computed from real sessions
    # (attendance_records), never a manually entered number. Threshold coloring
    # is applied by the caller (view layer) so this stays pure data.
    with connect() as c:
        return c.execute("""
            SELECT s.id AS subject_id, s.code AS subject_code, s.name AS subject_name,
                   COUNT(r.id) AS total_sessions,
                   SUM(CASE WHEN r.status='Present' THEN 1 ELSE 0 END) AS present_sessions
            FROM attendance_records r
            JOIN attendance_sessions a ON a.id=r.session_id
            JOIN subjects s ON s.id=a.subject_id
            WHERE r.roll_no=%s
            GROUP BY s.id
            ORDER BY s.name
        """, (roll_no,)).fetchall()


def student_subject_session_history(roll_no, subject_id):
    # — STUDENT Home, "tapping a subject shows session history for that
    # subject only (present/absent per date)" (SPEC.md §3).
    with connect() as c:
        return c.execute("""
            SELECT a.attendance_date, a.session_type, a.duration_hours, r.status
            FROM attendance_records r
            JOIN attendance_sessions a ON a.id=r.session_id
            WHERE r.roll_no=%s AND a.subject_id=%s
            ORDER BY a.attendance_date DESC
        """, (roll_no, subject_id)).fetchall()


def attendance_pct_band(present, total):
    """P2 req 9 thresholds: >=75 green/NORMAL, 50-74 amber/LOW, <50 red/CRITICAL."""
    if not total:
        return None, "muted"
    pct = present * 100 / total
    if pct >= 75:
        band = "green"
    elif pct >= 50:
        band = "yellow"
    else:
        band = "red"
    return round(pct, 1), band


def faculty_teaching_hours(faculty_username=None):
    # — P0-P1 req 7: computed from saved sessions, never manually entered.
    # 1hr class -> 1 session/1 hour. Lab (fixed 3hr) -> 1 session/3 hours.
    with connect() as c:
        sql = """
            SELECT a.faculty_username, u.full_name,
                   COUNT(*) AS sessions_taken,
                   SUM(a.duration_hours) AS teaching_hours,
                   SUM(CASE WHEN a.session_type='CLASS' THEN 1 ELSE 0 END) AS classes,
                   SUM(CASE WHEN a.session_type='LAB' THEN 1 ELSE 0 END) AS labs
            FROM attendance_sessions a
            LEFT JOIN users u ON u.username=a.faculty_username
        """
        args = []
        if faculty_username:
            sql += " WHERE a.faculty_username=%s"
            args.append(faculty_username)
        sql += " GROUP BY a.faculty_username, u.full_name ORDER BY teaching_hours DESC"
        return c.execute(sql, args).fetchall()


def recent_audit_logs(limit=100, entity=None):
    # — P0-P1 req 6: faculty audit trail visible to HOD. Read-only surface over
    # the existing audit_logs table; every write path already calls audit().
    # Filtered to actions performed by FACULTY users: this page exists so HOD
    # can review what faculty did (create/edit attendance, change topic, etc),
    # not to show the HOD's own login/logout/status-toggle activity back to
    # itself. audit() still writes every actor's actions to audit_logs
    # unfiltered — the filtering happens only at this read surface.
    with connect() as c:
        sql = (
            "SELECT a.username, a.action, a.entity, a.details, a.created_at "
            "FROM audit_logs a JOIN users u ON LOWER(u.username) = LOWER(a.username) "
            "WHERE u.role = 'FACULTY'"
        )
        args = []
        if entity:
            sql += " AND a.entity=%s"
            args.append(entity)
        sql += " ORDER BY a.created_at DESC LIMIT %s"
        args.append(limit)
        return c.execute(sql, args).fetchall()


def save_register(*, session_id, attendance, actor, role, session_type, duration_hours, topic):
    session = session_details(session_id)
    if not session:
        raise ValueError("Attendance session was not found")
    # Revalidate at the actual database-write boundary. Every save path must pass this.
    normalized_type, normalized_hours, normalized_topic = validate_session_payload(
        attendance_date=session["attendance_date"], semester_id=session["semester_id"],
        subject_id=session["subject_id"], faculty_username=session["faculty_username"],
        session_type=session_type, duration_hours=duration_hours, topic=topic,
    )
    if not session_is_editable(session, role):
        raise PermissionError("The 24-hour faculty edit window has expired. Contact HOD for correction.")
    if normalized_type != session["session_type"]:
        raise ValueError("Session type changed. Reopen the attendance setup before saving")
    with connect() as c:
        c.execute("UPDATE attendance_sessions SET duration_hours=%s,topic=%s,updated_at=CURRENT_TIMESTAMP WHERE id=%s",
                  (normalized_hours, normalized_topic, session_id))
        for roll_no, is_present in attendance.items():
            status = "Present" if is_present else "Absent"
            c.execute("""
                INSERT INTO attendance_records(session_id,roll_no,status,marked_by)
                VALUES(%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE
                    status=VALUES(status),marked_by=VALUES(marked_by),updated_at=CURRENT_TIMESTAMP
            """, (session_id, roll_no, status, actor))
        present = sum(bool(v) for v in attendance.values())
        audit(c, actor, "SAVE", "attendance_session",
              f"session={session_id}; type={normalized_type}; hours={normalized_hours}; present={present}; absent={len(attendance)-present}")
    return present, len(attendance) - present
