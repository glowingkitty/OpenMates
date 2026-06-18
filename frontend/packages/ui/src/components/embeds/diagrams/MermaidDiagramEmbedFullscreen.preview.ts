/**
 * Preview mock data for MermaidDiagramEmbedFullscreen.
 *
 * Uses the data-driven fullscreen shape that production embed routing passes to
 * direct embeds, including decoded Mermaid content and finished embed metadata.
 * Access at: /dev/preview/embeds/diagrams/MermaidDiagramEmbedFullscreen
 */

const diagramCode = `sequenceDiagram
    participant User
    participant Web as Web App
    participant API
    participant Mail as Email Service
    User->>Web: Enters email
    Web->>API: POST /auth/start-email
    API->>Mail: Send verification code
    Mail-->>User: Code arrives
    User->>Web: Enters code
    Web->>API: POST /auth/verify-email
    API-->>Web: Session token
    Web-->>User: Account ready`;

const decodedContent = {
  type: 'mermaid',
  app_id: 'diagrams',
  skill_id: 'mermaid',
  title: 'Email Verification Signup',
  diagram_kind: 'sequenceDiagram',
  diagram_code: diagramCode,
  line_count: diagramCode.split('\n').length,
  embed_ref: 'email-verification-signup-a1B',
  status: 'finished',
  version_number: 2
};

const defaultProps = {
  embedId: 'preview-diagrams-mermaid-fullscreen-1',
  onClose: () => {},
  hasPreviousEmbed: false,
  hasNextEmbed: false,
  data: {
    decodedContent,
    embedData: {
      status: 'finished',
      type: 'mermaid',
      app_id: 'diagrams',
      skill_id: 'mermaid'
    },
    attrs: {
      app_id: 'diagrams',
      skill_id: 'mermaid',
      type: 'mermaid'
    }
  }
};

export default defaultProps;

export const variants = {
  invalid_source: {
    ...defaultProps,
    embedId: 'preview-diagrams-mermaid-invalid',
    data: {
      ...defaultProps.data,
      decodedContent: {
        ...decodedContent,
        title: 'Invalid Mermaid Source',
        diagram_code: 'sequenceDiagram\n    User->>App Missing colon'
      }
    }
  }
};
