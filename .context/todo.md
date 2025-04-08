# 🗓️ Milestones

| ID  | Title             | Target Date | Tasks              | Status      |
|-----|-------------------|-------------|---------------------|-------------|
| M1  | MVP Setup         | 2025-04-20  | T1, T2, T6          | in-progress |
| M2  | MVP Auth          | 2025-04-28  | T3, T4, T5          | todo        |
| M3  | MVP UI            | 2025-05-05  | T7                  | todo        |
| M4  | v2 AI Assistant   | 2025-05-15  | T8                  | todo        |

---

## 📋 Milestone Descriptions

### M1 — MVP Setup  
Foundation work: initial repository, CI/CD, and team coding standards.

---

### M2 — MVP Auth  
Core authentication system: login, user DB, reset flows.

---

### M3 — MVP UI  
First user-facing interface: dashboard UI.

---

### M4 — v2 AI Assistant  
Optional AI assistant after auth + UI are done.

---

# ✅ Tasks

| ID   | Title                         | Priority | Status      | Depends on   | Milestone | Tags             |
|------|-------------------------------|----------|-------------|--------------|-----------|------------------|
| T1   | Setup GitHub repo             | High     | done        | –            | M1        | infra, devops    |
| T2   | Define coding standards       | High     | todo        | T1           | M1        | guidelines       |
| T3   | Add user login functionality  | High     | in-progress | T1           | M2        | auth, backend    |
| T4   | Create user database model    | High     | done        | T1           | M2        | database         |
| T5   | Implement password reset      | Medium   | todo        | T3, T4       | M2        | auth, UX         |
| T6   | Build deployment pipeline     | High     | todo        | T1           | M1        | devops, CI/CD    |
| T7   | Project overview dashboard    | Medium   | todo        | T3           | M3        | frontend         |
| T8   | Integrate AI assistant        | Low      | blocked     | T3, T7       | M4        | ai, UX           |

---

## 📝 Task Descriptions

### T2 — Define coding standards  
Define project-wide code rules: language choices, naming conventions, folder structure, use of classes vs functions, and test coverage requirements.

---

### T3 — Add user login functionality  
Frontend + backend for secure login using email/password and JWTs. Includes form validation, error handling, and session management.

---

### T5 — Implement password reset  
Add backend + frontend logic for password reset via email token. Includes token expiry, abuse prevention, and reset interface.

---

### T7 — Project overview dashboard  
Design and build dashboard shown post-login. Display key user info, status, and onboarding tips. Must integrate with auth.

---

### T8 — Integrate AI assistant  
Implement optional, privacy-aware AI assistant embedded in the UI. Blocked until login and dashboard are complete.
