/**
 * Preview mock data for MermaidDiagramEmbedPreview.
 *
 * Provides deterministic Mermaid source for the dev embed showcase so web E2E
 * and Apple contract capture can exercise Diagrams without invoking AI.
 * Access at: /dev/preview/embeds/diagrams/MermaidDiagramEmbedPreview
 */

const signupFlow = `sequenceDiagram
    participant User
    participant App
    participant API
    participant Email
    User->>App: Enter email address
    App->>API: Request verification code
    API->>Email: Send one-time code
    Email-->>User: Deliver code
    User->>App: Submit code
    App->>API: Verify code
    API-->>App: Create account session
    App-->>User: Show welcome screen`;

const defaultProps = {
  id: 'preview-diagrams-mermaid-1',
  title: 'Email Signup Sequence',
  diagram_kind: 'sequenceDiagram',
  diagram_code: signupFlow,
  line_count: signupFlow.split('\n').length,
  status: 'finished' as const,
  isMobile: false,
  onFullscreen: () => {}
};

export default defaultProps;

export const variants = {
  processing: {
    ...defaultProps,
    id: 'preview-diagrams-mermaid-processing',
    status: 'processing' as const,
    diagram_code: ''
  },
  error: {
    ...defaultProps,
    id: 'preview-diagrams-mermaid-error',
    status: 'error' as const,
    diagram_code: 'sequenceDiagram\n    User->>App Missing colon'
  },
  cancelled: {
    ...defaultProps,
    id: 'preview-diagrams-mermaid-cancelled',
    status: 'cancelled' as const,
    diagram_code: ''
  },
  flowchart: {
    ...defaultProps,
    id: 'preview-diagrams-mermaid-flowchart',
    title: 'Support Ticket Flow',
    diagram_kind: 'flowchart TD',
    diagram_code: `flowchart TD
    A[User reports issue] --> B{Can reproduce?}
    B -- Yes --> C[Create bug ticket]
    B -- No --> D[Ask for logs]
    C --> E[Prioritize fix]
    D --> B
    E --> F[Deploy patch]
    F --> G[Verify with user]`
  },
  mobile: {
    ...defaultProps,
    id: 'preview-diagrams-mermaid-mobile',
    isMobile: true
  }
};
