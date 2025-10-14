import type { Meta, StoryObj } from '@storybook/svelte';
import { GroupRenderer } from './GroupRenderer';
import type { EmbedNodeAttributes } from '../../../../../message_parsing/types';

// Create a mock component to demonstrate the GroupRenderer
const GroupRendererDemo = {
  template: `
    <div class="embed-demo">
      <h3>Group Renderer Demo</h3>
      <div class="renderer-output" id="renderer-output"></div>
    </div>
  `,
  mounted() {
    const renderer = new GroupRenderer();
    const output = document.getElementById('renderer-output');
    
    if (output) {
      // Create mock context
      const mockContext = {
        attrs: this.attrs,
        content: output,
        container: output
      };
      
      // Render the embed
      renderer.render(mockContext);
    }
  },
  props: ['attrs']
};

const meta: Meta<typeof GroupRendererDemo> = {
  title: 'Components/GroupRenderer',
  component: GroupRendererDemo,
  parameters: {
    layout: 'padded',
    docs: {
      description: {
        component: 'The GroupRenderer handles rendering of grouped embeds (website-group, code-group, doc-group, etc.) and delegates to individual renderers for each item in the group.'
      }
    }
  },
  argTypes: {
    attrs: {
      control: 'object',
      description: 'Embed node attributes'
    }
  },
  tags: ['autodocs']
};

export default meta;
type Story = StoryObj<typeof meta>;

// Sample embed attributes for different types
const websiteGroupAttrs: EmbedNodeAttributes = {
  id: 'website-group-1',
  type: 'web-website-group',
  status: 'finished',
  contentRef: 'group-1',
  contentHash: 'hash-1',
  groupedItems: [
    {
      id: 'website-1',
      type: 'web-website',
      status: 'finished',
      contentRef: 'website-1',
      contentHash: 'hash-1',
      url: 'https://example.com',
      title: 'Example Website',
      description: 'This is an example website for demonstration purposes.',
      favicon: 'https://example.com/favicon.ico',
      image: 'https://example.com/og-image.jpg'
    },
    {
      id: 'website-2',
      type: 'web-website',
      status: 'finished',
      contentRef: 'website-2',
      contentHash: 'hash-2',
      url: 'https://github.com',
      title: 'GitHub',
      description: 'The world\'s leading software development platform.',
      favicon: 'https://github.com/favicon.ico',
      image: 'https://github.com/og-image.jpg'
    }
  ],
  groupCount: 2
};

const codeGroupAttrs: EmbedNodeAttributes = {
  id: 'code-group-1',
  type: 'code-code-group',
  status: 'finished',
  contentRef: 'code-group-1',
  contentHash: 'hash-code-1',
  groupedItems: [
    {
      id: 'code-1',
      type: 'code-code',
      status: 'finished',
      contentRef: 'code-1',
      contentHash: 'hash-code-1',
      language: 'typescript',
      filename: 'example.ts',
      lineCount: 25,
      wordCount: 150
    },
    {
      id: 'code-2',
      type: 'code-code',
      status: 'finished',
      contentRef: 'code-2',
      contentHash: 'hash-code-2',
      language: 'javascript',
      filename: 'utils.js',
      lineCount: 15,
      wordCount: 80
    }
  ],
  groupCount: 2
};

const videoGroupAttrs: EmbedNodeAttributes = {
  id: 'video-group-1',
  type: 'videos-video-group',
  status: 'finished',
  contentRef: 'video-group-1',
  contentHash: 'hash-video-1',
  groupedItems: [
    {
      id: 'video-1',
      type: 'videos-video',
      status: 'finished',
      contentRef: 'video-1',
      contentHash: 'hash-video-1',
      url: 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
      title: 'Rick Astley - Never Gonna Give You Up'
    },
    {
      id: 'video-2',
      type: 'videos-video',
      status: 'finished',
      contentRef: 'video-2',
      contentHash: 'hash-video-2',
      url: 'https://www.youtube.com/watch?v=9bZkp7q19f0',
      title: 'PSY - GANGNAM STYLE'
    }
  ],
  groupCount: 2
};

export const WebsiteGroup: Story = {
  args: {
    attrs: websiteGroupAttrs
  }
};

export const CodeGroup: Story = {
  args: {
    attrs: codeGroupAttrs
  }
};

export const VideoGroup: Story = {
  args: {
    attrs: videoGroupAttrs
  }
};

export const SingleWebsite: Story = {
  args: {
    attrs: {
      id: 'website-single',
      type: 'web-website',
      status: 'finished',
      contentRef: 'website-single',
      contentHash: 'hash-single',
      url: 'https://svelte.dev',
      title: 'Svelte',
      description: 'Cybernetically enhanced web apps.',
      favicon: 'https://svelte.dev/favicon.ico',
      image: 'https://svelte.dev/og-image.jpg'
    }
  }
};

export const ProcessingState: Story = {
  args: {
    attrs: {
      ...websiteGroupAttrs,
      status: 'processing'
    }
  }
};

