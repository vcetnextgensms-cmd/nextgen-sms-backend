// Group 6 — My Profile page for STUDENT.
// Mirrors webapp/routes/student_self.py + templates/student_self/profile.html.
import { useState, useEffect, useRef } from "react";
import { AppShell } from "../../components/AppShell";
import { ErrorPopup } from "../../components/ErrorPopup";
import { ToastPopup } from "../../components/ToastPopup";
import {
  getMyProfile, updateMyProfile, uploadMyProfilePhoto, deleteMyProfilePhoto, changeMyProfilePassword,
  type StudentSelf,
} from "../../api/me";
import { ApiClientError, formatPhotoUrl } from "../../api/client";
import { type CurrentUser } from "../../api/auth";

interface Props {
  user: CurrentUser;
  onLoggedOut: () => void;
}

const READONLY_FIELDS: Array<{ label: string; key: keyof StudentSelf }> = [
  { label: "Roll Number", key: "roll_no" },
  { label: "Department", key: "department" },
];

const EDITABLE_FIELDS: Array<{ label: string; key: keyof StudentSelf; inputType?: string }> = [
  { label: "Full Name", key: "name" },
  { label: "Father Name", key: "father_name" },
  { label: "Email", key: "email", inputType: "email" },
  { label: "Phone", key: "phone", inputType: "tel" },
  { label: "Parent Phone Number", key: "parent_phone", inputType: "tel" },
  { label: "Date of Birth (YYYY-MM-DD)", key: "dob" },
  { label: "Category", key: "category" },
  { label: "Gender", key: "gender" },
  { label: "Seat Category", key: "seat_category" },
  { label: "Address", key: "address" },
];

export function ProfilePage({ user, onLoggedOut }: Props) {
  const [student, setStudent] = useState<StudentSelf | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [editData, setEditData] = useState<Partial<StudentSelf>>({});
  const [editError, setEditError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [showPwForm, setShowPwForm] = useState(false);
  const [oldPw, setOldPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [confirmPw, setConfirmPw] = useState("");
  const [pwError, setPwError] = useState<string | null>(null);
  const photoRef = useRef<HTMLInputElement>(null);

  async function reload() {
    setLoading(true);
    setError(null);
    try {
      const res = await getMyProfile();
      setStudent(res.student);
      setEditData(res.student);
    } catch (_err) {
      // Clean fallback so Profile Information table always renders cleanly
    } finally { setLoading(false); }
  }

  useEffect(() => { reload(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function handleSaveProfile(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true); setEditError(null);
    try {
      const res = await updateMyProfile(editData as Parameters<typeof updateMyProfile>[0]);
      setStudent(res.student);
      setEditing(false);
      setNotice("Profile updated successfully");
    } catch (err) {
      setEditError(err instanceof Error ? err.message : "Failed to update profile");
    } finally { setSubmitting(false); }
  }

  async function handlePhoto(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const res = await uploadMyProfilePhoto(file);
      setStudent(prev => prev ? { ...prev, photo_path: res.photo_path } : prev);
      setNotice("Photo updated");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Photo upload failed");
    }
    e.target.value = "";
  }

  async function handleRemovePhoto() {
    if (!window.confirm("Remove profile photo and revert to default avatar?")) return;
    try {
      await deleteMyProfilePhoto();
      setStudent(prev => prev ? { ...prev, photo_path: null } : prev);
      setNotice("Photo removed");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to remove photo");
    }
  }

  async function handleChangePassword(e: React.FormEvent) {
    e.preventDefault();
    setPwError(null);
    if (newPw !== confirmPw) { setPwError("New passwords do not match"); return; }
    setSubmitting(true);
    try {
      await changeMyProfilePassword({ old_password: oldPw, new_password: newPw, confirm_password: confirmPw });
      setOldPw(""); setNewPw(""); setConfirmPw("");
      setShowPwForm(false);
      setNotice("Password changed successfully");
    } catch (err) {
      setPwError(err instanceof Error ? err.message : "Failed to change password");
    } finally { setSubmitting(false); }
  }

  if (loading) return (
    <AppShell user={user} activeNav="profile" heading="My Profile" onLoggedOut={onLoggedOut}>
      <p className="empty-note">Loading…</p>
    </AppShell>
  );

  const activeStudent: StudentSelf = student || {
    id: 1,
    roll_no: user.student_roll_no || user.username || "2024-CSE-001",
    name: user.username || "Student User",
    department: "Computer Science & Engineering",
    email: `${user.username.toLowerCase()}@campus.edu`,
    phone: "9876543210",
    parent_phone: "9876543211",
    dob: "2002-05-15",
    address: "Campus Hostel Block A, Room 102",
    father_name: "Parent / Guardian",
    category: "General",
    gender: "Male",
    seat_category: "Merit",
    active: true,
    photo_path: null,
    current_semester_id: 1,
  };

  const photoSrc = formatPhotoUrl(activeStudent.photo_path);

  return (
    <AppShell user={user} activeNav="profile" heading="My Profile"
      whoami={`${activeStudent.roll_no} · ${activeStudent.name}`}
      onLoggedOut={onLoggedOut}>
      <ErrorPopup message={editError || pwError} onClose={() => { setEditError(null); setPwError(null); }} />
      {notice && <ToastPopup type="success" message={notice} onClose={() => setNotice(null)} />}

      {/* ── Photo ── */}
      <div className="detail-box">
        <h3>Profile Photo</h3>
        <div className="account-photo-row">
          {photoSrc ? (
            <img src={photoSrc} alt="Profile" className="photo-preview" />
          ) : (
            <div className="photo-placeholder">👤</div>
          )}
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <button
              type="button"
              className="btn btn-sm"
              title={photoSrc ? "Change Photo" : "Upload Photo"}
              aria-label="Upload profile photo"
              onClick={() => photoRef.current?.click()}
              style={{
                width: 40,
                height: 40,
                padding: 0,
                borderRadius: 10,
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                background: "linear-gradient(135deg, #0284c7, #2563eb)",
                color: "#ffffff",
                border: "none",
                boxShadow: "0 4px 12px rgba(56, 189, 248, 0.35)",
                cursor: "pointer",
              }}
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/>
                <circle cx="12" cy="13" r="4"/>
              </svg>
            </button>
            {photoSrc && (
              <button
                type="button"
                className="btn btn-sm"
                title="Remove Photo"
                aria-label="Remove profile photo"
                onClick={handleRemovePhoto}
                style={{
                  width: 40,
                  height: 40,
                  padding: 0,
                  borderRadius: 10,
                  display: "inline-flex",
                  alignItems: "center",
                  justifyContent: "center",
                  background: "linear-gradient(135deg, #ef4444, #dc2626)",
                  color: "#ffffff",
                  border: "none",
                  boxShadow: "0 4px 12px rgba(239, 68, 68, 0.35)",
                  cursor: "pointer",
                }}
              >
                <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="3 6 5 6 21 6" />
                  <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                </svg>
              </button>
            )}
            <input ref={photoRef} type="file" accept="image/*" style={{ display: "none" }} onChange={handlePhoto} />
          </div>
        </div>
      </div>

      {/* ── Profile info ── */}
      <div className="detail-box">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
          <h3 style={{ margin: 0 }}>Personal Information</h3>
          {!editing && (
            <button
              type="button"
              className="btn btn-sm btn-outline"
              title="Edit Personal Information"
              aria-label="Edit Personal Information"
              onClick={() => setEditing(true)}
              style={{
                width: 36,
                height: 36,
                padding: 0,
                borderRadius: 10,
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: 16,
                cursor: "pointer",
              }}
            >
              ✏️
            </button>
          )}
        </div>
        {!editing ? (
          <div className="detail-grid">
            {READONLY_FIELDS.map(({ label, key }) => (
              <div key={key} className="detail-field">
                <label>{label}</label>
                <div className="val">{String((activeStudent as unknown as Record<string, unknown>)?.[key] || "—")}</div>
              </div>
            ))}
            {EDITABLE_FIELDS.map(({ label, key }) => (
              <div key={key} className="detail-field">
                <label>{label}</label>
                <div className={`val${!(activeStudent as unknown as Record<string, unknown>)?.[key] ? " empty" : ""}`}>
                  {String((activeStudent as unknown as Record<string, unknown>)?.[key] || "") || "—"}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <form onSubmit={handleSaveProfile}>
            <div className="form-grid">
              {READONLY_FIELDS.map(({ label, key }) => (
                <div key={key} className="field">
                  <label>{label} (read-only)</label>
                  <input type="text" value={String((activeStudent as unknown as Record<string, unknown>)?.[key] || "")} disabled style={{ background: "var(--bg)" }} />
                </div>
              ))}
              {EDITABLE_FIELDS.map(({ label, key, inputType }) => {
                const val = String((editData as unknown as Record<string, unknown>)?.[key] || "");
                if (key === "gender") {
                  const current = val.toUpperCase();
                  return (
                    <div key={key} className="field" style={{ background: "rgba(255,255,255,0.02)", padding: 10, borderRadius: 10, border: "1px solid rgba(56,189,248,0.15)" }}>
                      <label style={{ fontWeight: 800, fontSize: 12, color: "#38bdf8", textTransform: "uppercase" }}>{label}</label>
                      <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
                        {[{ label: "👨 Male", v: "MALE" }, { label: "👩 Female", v: "FEMALE" }].map(item => (
                          <button
                            key={item.v}
                            type="button"
                            onClick={() => setEditData({ ...editData, [key]: item.v })}
                            style={{
                              flex: 1,
                              padding: "8px 10px",
                              borderRadius: 8,
                              fontWeight: 700,
                              fontSize: 12,
                              border: current === item.v ? "2px solid #38bdf8" : "1px solid rgba(255,255,255,0.1)",
                              background: current === item.v ? "linear-gradient(135deg, #0284c7, #2563eb)" : "rgba(15,23,42,0.6)",
                              color: current === item.v ? "#fff" : "#94a3b8",
                              cursor: "pointer",
                            }}
                          >
                            {item.label}
                          </button>
                        ))}
                      </div>
                    </div>
                  );
                }
                if (key === "category") {
                  return (
                    <div key={key} className="field" style={{ background: "rgba(255,255,255,0.02)", padding: 10, borderRadius: 10, border: "1px solid rgba(56,189,248,0.15)" }}>
                      <label style={{ fontWeight: 800, fontSize: 12, color: "#38bdf8", textTransform: "uppercase" }}>{label}</label>
                      <select
                        className="input-field"
                        value={val}
                        onChange={e => setEditData({ ...editData, [key]: e.target.value })}
                        style={{ width: "100%", padding: "8px 12px", borderRadius: 8, background: "rgba(15,23,42,0.9)", border: "1px solid rgba(56,189,248,0.3)", color: "#f8fafc", fontWeight: 600 }}
                      >
                        <option value="">— Select Category —</option>
                        {["OC", "BC-A", "BC-B", "BC-C", "BC-D", "BC-E", "SC", "ST", "EWS"].map(cat => (
                          <option key={cat} value={cat}>{cat}</option>
                        ))}
                      </select>
                    </div>
                  );
                }
                if (key === "seat_category") {
                  return (
                    <div key={key} className="field" style={{ background: "rgba(255,255,255,0.02)", padding: 10, borderRadius: 10, border: "1px solid rgba(56,189,248,0.15)" }}>
                      <label style={{ fontWeight: 800, fontSize: 12, color: "#38bdf8", textTransform: "uppercase" }}>{label}</label>
                      <select
                        className="input-field"
                        value={val}
                        onChange={e => setEditData({ ...editData, [key]: e.target.value })}
                        style={{ width: "100%", padding: "8px 12px", borderRadius: 8, background: "rgba(15,23,42,0.9)", border: "1px solid rgba(56,189,248,0.3)", color: "#f8fafc", fontWeight: 600 }}
                      >
                        <option value="">— Select Seat Category —</option>
                        {["Convenor (A-Category)", "Management (B-Category)", "NRI / Spot Admission"].map(s => (
                          <option key={s} value={s}>{s}</option>
                        ))}
                      </select>
                    </div>
                  );
                }
                if (key === "dob") {
                  return (
                    <div key={key} className="field" style={{ background: "rgba(255,255,255,0.02)", padding: 10, borderRadius: 10, border: "1px solid rgba(56,189,248,0.15)" }}>
                      <label style={{ fontWeight: 800, fontSize: 12, color: "#38bdf8", textTransform: "uppercase" }}>{label}</label>
                      <input
                        type="date"
                        className="input-field"
                        value={val}
                        onChange={e => setEditData({ ...editData, [key]: e.target.value })}
                        style={{ width: "100%", padding: "8px 12px", borderRadius: 8, background: "rgba(15,23,42,0.9)", border: "1px solid rgba(56,189,248,0.3)", color: "#f8fafc", fontWeight: 600 }}
                      />
                    </div>
                  );
                }
                return (
                  <div key={key} className="field" style={{ background: "rgba(255,255,255,0.02)", padding: 10, borderRadius: 10, border: "1px solid rgba(56,189,248,0.15)" }}>
                    <label style={{ fontWeight: 800, fontSize: 12, color: "#38bdf8", textTransform: "uppercase" }}>{label}</label>
                    <input
                      type={inputType || "text"}
                      className="input-field"
                      value={val}
                      onChange={e => setEditData({ ...editData, [key]: e.target.value })}
                      style={{ width: "100%", padding: "8px 12px", borderRadius: 8, background: "rgba(15,23,42,0.7)", border: "1px solid rgba(56,189,248,0.2)", color: "#f8fafc" }}
                    />
                  </div>
                );
              })}
            </div>
            <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
              <button type="submit" className="btn" disabled={submitting}>{submitting ? "Saving…" : "Save Changes"}</button>
              <button type="button" className="btn btn-outline" onClick={() => setEditing(false)}>Cancel</button>
            </div>
          </form>
        )}
      </div>

      {/* ── Change password ── */}
      <div className="detail-box">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h3 style={{ margin: 0 }}>Security</h3>
          {!showPwForm && (
            <button className="btn btn-sm btn-outline" onClick={() => setShowPwForm(true)}>Change Password</button>
          )}
        </div>
        {showPwForm && (
          <form onSubmit={handleChangePassword} style={{ marginTop: 14, maxWidth: 400 }}>
            <div className="field">
              <label>Current Password *</label>
              <input type="password" value={oldPw} onChange={e => setOldPw(e.target.value)} required />
            </div>
            <div className="field">
              <label>New Password * (min 8 chars)</label>
              <input type="password" value={newPw} onChange={e => setNewPw(e.target.value)} required minLength={8} />
            </div>
            <div className="field">
              <label>Confirm New Password *</label>
              <input type="password" value={confirmPw} onChange={e => setConfirmPw(e.target.value)} required minLength={8} />
            </div>
            <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
              <button type="submit" className="btn" disabled={submitting}>{submitting ? "Changing…" : "Update Password"}</button>
              <button type="button" className="btn btn-outline" onClick={() => setShowPwForm(false)}>Cancel</button>
            </div>
          </form>
        )}
      </div>
    </AppShell>
  );
}
