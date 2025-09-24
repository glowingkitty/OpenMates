import type { Meta, StoryObj } from '@storybook/svelte';
import MessageInput from './MessageInput.svelte';

interface MessageInputProps {
  currentChatId?: string;
  isFullscreen?: boolean;
  hasContent?: boolean;
}

const meta: Meta<MessageInputProps> = {
  title: 'Components/MessageInput',
  component: MessageInput,
  parameters: {
    layout: 'fullscreen',
    docs: {
      description: {
        component: 'The main message input component for composing and sending messages with rich text editing, file uploads, and embed support.'
      }
    }
  },
  argTypes: {
    isFullscreen: {
      control: 'boolean',
      description: 'Whether the input is in fullscreen mode'
    }
  },
  tags: ['autodocs']
};

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: {}
};

export const Fullscreen: Story = {
  args: {
    isFullscreen: true
  },
  parameters: {
    layout: 'fullscreen'
  }
};
