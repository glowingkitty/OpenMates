import { renderPublicationMarkdown } from '../../publications/publicationMarkdown';
import { newsroomFixtures } from './fixtures';

/** Public, synthetic source verifies the same renderer used by live articles. */
export const publicationCodeFixture = {
  ...newsroomFixtures.en,
  blogArticle: {
    ...newsroomFixtures.en.blogArticle,
    intro: 'Code examples remain readable in both themes.',
    bodyHtml: renderPublicationMarkdown([
      '```typescript',
      'const message: string = "Hello OpenMates";',
      'console.log(message); // A safe example',
      '```',
      '```python',
      'def greet(name):',
      '    return "Hello " + name',
      '```',
      '```bash',
      'echo "Hello OpenMates"',
      '```',
      '```json',
      '{ "enabled": true, "count": 3 }',
      '```',
      '```unknown-language',
      '<script>alert("This is displayed as text")</script>',
      '```',
      '```typescript',
      'const longMessage = "' + 'Long lines scroll inside the code block. '.repeat(12) + '";',
      '```',
    ].join('\n')),
  },
};
