<!--
  frontend/packages/ui/src/components/embeds/electronics/PcbSchematicEmbedPreview.svelte

  Electronics PCB schematic preview. It intentionally delegates source rendering
  to CodeEmbedPreview so line previews, highlighting, PII behavior, and responsive
  layout stay in lockstep with the code-code embed.
-->

<script lang="ts">
  import CodeEmbedPreview from '../code/CodeEmbedPreview.svelte';

  interface Props {
    id: string;
    language?: string;
    filename?: string;
    lineCount?: number;
    line_count?: number;
    status: 'processing' | 'finished' | 'error';
    taskId?: string;
    task_id?: string;
    isMobile?: boolean;
    onFullscreen: () => void;
    codeContent?: string;
    code?: string;
  }

  let {
    id,
    language = 'atopile',
    filename,
    lineCount,
    line_count,
    status,
    taskId,
    task_id,
    isMobile = false,
    onFullscreen,
    codeContent,
    code,
  }: Props = $props();
</script>

<CodeEmbedPreview
  {id}
  language={language || 'atopile'}
  {filename}
  lineCount={lineCount ?? line_count ?? 0}
  {status}
  taskId={taskId ?? task_id}
  {isMobile}
  {onFullscreen}
  codeContent={codeContent ?? code ?? ''}
  appId="electronics"
  skillId="schematic"
  skillIconName="pcbdesign"
/>
