// Group 6 — My Account page for HOD and FACULTY.
// Mirrors webapp/routes/self_profile.py + templates/self_profile/account.html.
import { useState, useEffect, useRef } from "react";
import { AppShell } from "../../components/AppShell";
import { ErrorPopup } from "../../components/ErrorPopup";
import { ToastPopup } from "../../components/ToastPopup";
import {
  getMyAccount, updateMyAccount, uploadMyAccountPhoto, deleteMyAccountPhoto, changeMyAccountPassword,
  type StaffUser,
} from "../../api/me";
import { ApiClientError, formatPhotoUrl } from "../../api/client";
import { type CurrentUser } from "../../api/auth";

interface Props {
  user: CurrentUser;
  onLoggedOut: () => void;
}

const PROFILE_FIELDS: Array<{ label: string; key: keyof StaffUser; inputType?: string }> = [
  { label: "Full Name", key: "full_name" },
  { label: "Department", key: "department" },
  { label: "Designation", key: "designation" },
  { label: "Employee ID", key: "employee_id" },
  { label: "Email", key: "email", inputType: "email" },
  { label: "Phone", key: "phone", inputType: "tel" },
  { label: "Qualification", key: "qualification" },
  { label: "Date of Joining (YYYY-MM-DD)", key: "date_of_joining" },
];

export function AccountPage({ user, onLoggedOut }: Props) {
  const [staffUser, setStaffUser] = useState<StaffUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [editData, setEditData] = useState<Partial<StaffUser>>({});
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
      const res = await getMyAccount();
      setStaffUser(res.user as StaffUser);
      setEditData(res.user as StaffUser);
    } catch (_err) {
      // Clean load fallback
    } finally { setLoading(false); }
  }

  useEffect(() => { reload(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function handleSaveProfile(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true); setEditError(null);
    try {
      const res = await updateMyAccount(editData as Parameters<typeof updateMyAccount>[0]);
      setStaffUser(res.user as StaffUser);
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
      const res = await uploadMyAccountPhoto(file);
      setStaffUser(prev => prev ? { ...prev, photo_path: res.photo_path } : prev);
      setNotice("Photo updated");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Photo upload failed");
    }
    e.target.value = "";
  }

  async function handleRemovePhoto() {
    if (!window.confirm("Remove profile photo and revert to default avatar?")) return;
    try {
      await deleteMyAccountPhoto();
      setStaffUser(prev => prev ? { ...prev, photo_path: null } : prev);
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
      await changeMyAccountPassword({ old_password: oldPw, new_password: newPw, confirm_password: confirmPw });
      setOldPw(""); setNewPw(""); setConfirmPw("");
      setShowPwForm(false);
      setNotice("Password changed successfully");
    } catch (err) {
      setPwError(err instanceof Error ? err.message : "Failed to change password");
    } finally { setSubmitting(false); }
  }

  if (loading) return (
    <AppShell user={user} activeNav="account" heading="My Account" onLoggedOut={onLoggedOut}>
      <p className="empty-note">Loading…</p>
    </AppShell>
  );

  const photoSrc = formatPhotoUrl(staffUser?.photo_path ?? null);

  return (
    <AppShell user={user} activeNav="account" heading="My Account" onLoggedOut={onLoggedOut}>
      <ErrorPopup message={error || editError || pwError} onClose={() => { setError(null); setEditError(null); setPwError(null); }} />
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
          <h3 style={{ margin: 0 }}>Profile Information</h3>
          {!editing && (
            <button
              type="button"
              className="btn btn-sm btn-outline"
              title="Edit Profile Information"
              aria-label="Edit Profile"
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
            {PROFILE_FIELDS.map(({ label, key }) => (
              <div key={key} className="detail-field">
                <label>{label}</label>
                <div className={`val${!(staffUser as unknown as Record<string, unknown>)?.[key] ? " empty" : ""}`}>
                  {String((staffUser as unknown as Record<string, unknown>)?.[key] || "") || "—"}
                </div>
              </div>
            ))}
            <div className="detail-field">
              <label>Username</label>
              <div className="val">{staffUser?.username}</div>
            </div>
            <div className="detail-field">
              <label>Role</label>
              <div className="val">
                <span className="chip chip-yellow">
                  {staffUser?.role === "HOD" || (staffUser?.role as string) === "ADMIN" ? "Developer (HOD/Admin)" : staffUser?.role}
                </span>
              </div>
            </div>
          </div>
        ) : (
          <form onSubmit={handleSaveProfile}>
            <div className="form-grid">
              {PROFILE_FIELDS.map(({ label, key, inputType }) => (
                <div key={key} className="field">
                  <label>{label}</label>
                  <input
                    type={inputType || "text"}
                    value={String((editData as unknown as Record<string, unknown>)?.[key] || "")}
                    onChange={e => setEditData({ ...editData, [key]: e.target.value })}
                  />
                </div>
              ))}
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
