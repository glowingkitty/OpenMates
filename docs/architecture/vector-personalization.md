# 🧠 Client-Side Vector Search for Privacy-Preserving Personalization

## Overview

This feature enables **privacy-focused personalization** in the AI Agents web app using **client-side vector search**.  
Instead of storing user interests or profiles on the server, the system performs **semantic matching locally** to determine which of the user’s interests are relevant to each message.

Only the **relevant tags** are shared with the backend — not the user’s entire interest profile — providing personalization **without user tracking**.

---

## ✨ How It Works

### 1. Setup Phase
During onboarding, the user selects or describes topics they’re interested in.  
These interest statements are converted into vector embeddings and stored **locally** (e.g., in IndexedDB or SQLite-WASM).  
No data leaves the device.

Example:
```json
{
  "user_interests": ["AI safety", "automation", "neuroscience", "history podcasts"]
}

2. Message Processing
	1.	The user sends a message to the server.
	2.	A lightweight preprocessing step returns a list of semantic tags for that message (e.g., "AI tools", "ethics", "productivity").
	3.	On the client, a local vector search compares these tags against the stored user interest embeddings.
	4.	The top-N most relevant interests are selected and sent to the backend as part of the inference request.

Only those contextually relevant topics (as plain text) are sent — not vectors or the full profile.

⸻

🧩 Example Flow

flowchart LR
    A[User selects interests] --> B[Embeddings generated locally]
    B --> C[Interests stored in local vector DB]
    D[User sends message] --> E[Server preprocessing → message tags]
    E --> F[Client performs vector similarity search]
    F --> G[Top relevant interests identified]
    G --> H[Relevant interests sent with LLM request]
    H --> I[Personalized LLM response]


⸻

⚙️ Technology

Component	Example Options
Embeddings	text-embedding-3-small, MiniLM-L6-v2 (local)
Vector Store	hnswlib-wasm, vectordb, or SQLite-VSS
Storage	IndexedDB or WASM SQLite
Backend	Stateless LLM inference API


⸻

🔒 Privacy Advantages
	•	No server-side storage of user interests or embeddings
	•	Only minimal, relevant metadata sent per request
	•	Difficult or impossible to reconstruct full user profile
	•	Complies with privacy-first design principles (GDPR-friendly)

⸻

⚡ Performance

Client-side vector searches are lightweight:
	•	<10 ms for <10 000 interests
	•	Local embeddings cached for fast access
	•	No network overhead for personalization logic

⸻

✅ Benefits
	•	Personalization without profiling
	•	Low latency, high privacy
	•	Semantic understanding of user preferences
	•	Simple integration with existing LLM APIs

⸻

🧠 Future Improvements
	•	Optional encrypted local backups for interests
	•	Model versioning to prevent embedding drift
	•	Local embedding generation using transformers.js for full offline mode

⸻

Example Output

{
  "message": "How can I build an autonomous research assistant?",
  "tags": ["AI tools", "automation", "agents"],
  "matched_interests": ["AI safety", "automation"],
  "response": "To build a safe autonomous research assistant..."
}