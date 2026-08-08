"""Absentee SMS queue (HANDOFF.md Item A).

Transport: USB/serial GSM modem on the machine running the FastAPI app
(department-owned phone/dongle, AT-command SMS send) — see webapp/sms_modem.py.

This module only owns the DB-backed queue: writing PENDING rows when
attendance is saved, and marking them SENT/FAILED once a send attempt is
made. It is deliberately transport-agnostic (webapp/sms_worker.py calls
webapp/sms_modem.py and updates status via mark_sent/mark_failed below) so
the queue logic is correct independent of whether real hardware is
attached.

Rules (confirmed with Boss, 2026-07-20):
- One SMS per student per day maximum, even if absent in multiple periods
  the same day. Enforced by UNIQUE(roll_no, send_date) on sms_queue —
  queueing a second absence for a student already queued/sent that date is
  a silent no-op (INSERT OR IGNORE), not an error.
- 62/day ceiling (matches CSD headcount) — belt-and-suspenders check on top
  of the per-student dedup, which already makes 62 the natural max with 62
  active students. Configurable via settings key 'sms_daily_cap'.
- Message wording is fixed, confirmed with Boss — do not reword:
  "Dear Parent, {student} was absent for {subject} on {date}. - VCET CSD Dept"
"""
from database import audit, connect, get_setting

MESSAGE_TEMPLATE = "Dear Parent, {student} is absent for class today ({subject}, {date}). - VCET CSD Dept"


def queue_absentees_for_session(session_id, absent_roll_nos, actor="system"):
    """Call this right after save_register() succeeds, passing only the
    roll numbers whose status is 'Absent' in that save. Does not touch
    attendance_service.py — kept as a separate add-on per HANDOFF's
    "add a queue insert alongside it, don't duplicate that logic" note.

    Returns (queued_count, skipped_no_phone_count).
    """
    if not absent_roll_nos:
        return 0, 0
    with connect() as c:
        session = c.execute("""
            SELECT a.attendance_date, s.name AS subject_name
            FROM attendance_sessions a JOIN subjects s ON s.id=a.subject_id
            WHERE a.id=%s
        """, (session_id,)).fetchone()
        if not session:
            return 0, 0
        send_date = session["attendance_date"]
        cap = int(get_setting("sms_daily_cap", "62") or 62)
        already_row = c.execute(
            "SELECT COUNT(*) AS n FROM sms_queue WHERE send_date=%s", (send_date,)
        ).fetchone()
        already_today = already_row["n"] if already_row else 0
        queued, skipped = 0, 0
        for roll_no in absent_roll_nos:
            if already_today + queued >= cap:
                break
            student = c.execute(
                "SELECT name, parent_phone FROM students WHERE roll_no=%s", (roll_no,)
            ).fetchone()
            if not student or not (student["parent_phone"] or "").strip():
                skipped += 1
                continue
            message = MESSAGE_TEMPLATE.format(
                student=student["name"], subject=session["subject_name"], date=send_date
            )
            cur = c.execute("""
                INSERT IGNORE INTO sms_queue(roll_no,parent_phone,message,attendance_session_id,send_date)
                VALUES(%s,%s,%s,%s,%s)
            """, (roll_no, student["parent_phone"], message, session_id, send_date))
            if cur.rowcount:
                queued += 1
        if queued:
            audit(c, actor, "SMS_QUEUED", "attendance_session", f"session={session_id}; queued={queued}; skipped_no_phone={skipped}")
        return queued, skipped


def pending_sms(limit=25):
    with connect() as c:
        return c.execute(
            "SELECT * FROM sms_queue WHERE status='PENDING' ORDER BY created_at LIMIT %s", (limit,)
        ).fetchall()


def mark_sent(sms_id, actor="system"):
    with connect() as c:
        row = c.execute("SELECT roll_no FROM sms_queue WHERE id=%s", (sms_id,)).fetchone()
        c.execute("UPDATE sms_queue SET status='SENT', sent_at=CURRENT_TIMESTAMP, error=NULL WHERE id=%s", (sms_id,))
        if row:
            audit(c, actor, "SMS_SENT", "student", row["roll_no"])


def mark_failed(sms_id, error, actor="system"):
    with connect() as c:
        row = c.execute("SELECT roll_no FROM sms_queue WHERE id=%s", (sms_id,)).fetchone()
        c.execute("UPDATE sms_queue SET status='FAILED', error=%s WHERE id=%s", (str(error)[:300], sms_id))
        if row:
            audit(c, actor, "SMS_FAILED", "student", f"{row['roll_no']}: {str(error)[:200]}")


def recent_sms(limit=100):
    with connect() as c:
        return c.execute("""
            SELECT q.*, s.name AS student_name
            FROM sms_queue q LEFT JOIN students s ON s.roll_no=q.roll_no
            ORDER BY q.created_at DESC LIMIT %s
        """, (limit,)).fetchall()
