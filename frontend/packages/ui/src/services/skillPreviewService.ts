// frontend/packages/ui/src/services/skillPreviewService.ts
// Service for managing app skill preview state and WebSocket updates

import { webSocketService } from './websocketService';
import type { SkillExecutionStatusUpdatePayload, WebSearchSkillPreviewData, VideoTranscriptSkillPreviewData } from '../types/appSkills';

/**
 * Map of task IDs to preview data
 * Key: task_id, Value: preview data (can be WebSearchSkillPreviewData or VideoTranscriptSkillPreviewData)
 */
const skillPreviewCache = new Map<string, WebSearchSkillPreviewData | VideoTranscriptSkillPreviewData>();

/**
 * Payload for skill cancellation confirmation from backend
 */
interface SkillCancelRequestedPayload {
  skill_task_id: string;
  embed_id?: string;
  status: string; // 'cancellation_requested'
}

/**
 * Event target for skill preview updates
 */
class SkillPreviewService extends EventTarget {
  /**
   * Stored handler reference for unregistering
   */
  private skillStatusHandler?: (payload: SkillExecutionStatusUpdatePayload) => void;
  
  /**
   * Handler for skill cancellation confirmation
   */
  private skillCancelHandler?: (payload: SkillCancelRequestedPayload) => void;
  
  /**
   * Register WebSocket handlers for skill execution updates
   */
  registerWebSocketHandlers(): void {
    console.debug('[SkillPreviewService] Registering WebSocket handlers');
    
    // Store handler reference for unregistering
    this.skillStatusHandler = (payload: SkillExecutionStatusUpdatePayload) => {
      this.handleSkillStatusUpdate(payload);
    };
    
    // Handler for skill cancellation confirmation from backend
    this.skillCancelHandler = (payload: SkillCancelRequestedPayload) => {
      this.handleSkillCancelRequested(payload);
    };
    
    // Handler for skill execution status updates
    webSocketService.on('skill_execution_status', this.skillStatusHandler);
    
    // Handler for skill cancellation confirmation
    // Backend sends this when cancel_skill request is processed
    webSocketService.on('skill_cancel_requested', this.skillCancelHandler);
  }
  
  /**
   * Unregister WebSocket handlers
   */
  unregisterWebSocketHandlers(): void {
    console.debug('[SkillPreviewService] Unregistering WebSocket handlers');
    if (this.skillStatusHandler) {
      webSocketService.off('skill_execution_status', this.skillStatusHandler);
      this.skillStatusHandler = undefined;
    }
    if (this.skillCancelHandler) {
      webSocketService.off('skill_cancel_requested', this.skillCancelHandler);
      this.skillCancelHandler = undefined;
    }
  }
  
  /**
   * Handle skill cancellation confirmation from backend
   * This is sent when the backend has processed a cancel_skill request
   */
  private handleSkillCancelRequested(payload: SkillCancelRequestedPayload): void {
    console.debug('[SkillPreviewService] Received skill cancellation confirmation:', payload);
    
    const { skill_task_id, embed_id, status } = payload;
    
    if (!skill_task_id) {
      console.warn('[SkillPreviewService] Skill cancellation payload missing skill_task_id');
      return;
    }
    
    // Update preview data if it exists
    const existingPreviewData = skillPreviewCache.get(skill_task_id);
    if (existingPreviewData) {
      existingPreviewData.status = 'cancelled';
      skillPreviewCache.set(skill_task_id, existingPreviewData);
    }
    
    // Dispatch event for UI updates (e.g., embed previews can react to cancellation)
    this.dispatchEvent(new CustomEvent('skillCancelled', {
      detail: {
        skill_task_id,
        embed_id,
        status
      }
    }));
  }
  
  /**
   * Handle skill execution status update from WebSocket
   */
  private handleSkillStatusUpdate(payload: SkillExecutionStatusUpdatePayload): void {
    console.debug('[SkillPreviewService] Received skill status update:', payload);
    
    const { task_id, app_id, skill_id, status, preview_data } = payload;
    
    if (!task_id) {
      console.warn('[SkillPreviewService] Skill status update missing task_id');
      return;
    }
    
    // Update or create preview data
    let previewData: WebSearchSkillPreviewData | VideoTranscriptSkillPreviewData;
    
    if (skillPreviewCache.has(task_id)) {
      // Update existing preview data
      previewData = skillPreviewCache.get(task_id)!;
      previewData.status = status;
      
      // Merge preview_data if provided
      if (preview_data) {
        Object.assign(previewData, preview_data);
      }
    } else {
      // Create new preview data based on skill type
      if (app_id === 'web' && skill_id === 'search') {
        previewData = {
          app_id: 'web',
          skill_id: 'search',
          status,
          task_id,
          query: (preview_data as any)?.query || '',
          provider: (preview_data as any)?.provider || 'Brave Search',
          ...(preview_data as any)
        } as WebSearchSkillPreviewData;
      } else if (app_id === 'videos' && skill_id === 'get_transcript') {
        previewData = {
          app_id: 'videos',
          skill_id: 'get_transcript',
          status,
          task_id,
          video_count: (preview_data as any)?.video_count || 0,
          success_count: (preview_data as any)?.success_count || 0,
          failed_count: (preview_data as any)?.failed_count || 0,
          results: (preview_data as any)?.results || [],
          ...(preview_data as any)
        } as VideoTranscriptSkillPreviewData;
      } else {
        // Generic preview data for other skills
        previewData = {
          app_id,
          skill_id,
          status,
          task_id,
          ...(preview_data as any)
        } as WebSearchSkillPreviewData;
      }
    }
    
    // Update cache
    skillPreviewCache.set(task_id, previewData);
    
    // Dispatch event for UI updates
    this.dispatchEvent(new CustomEvent('skillPreviewUpdate', {
      detail: {
        task_id,
        previewData,
        chat_id: payload.chat_id,
        message_id: payload.message_id
      }
    }));
  }
  
  /**
   * Get preview data for a task ID
   */
  getPreviewData(taskId: string): WebSearchSkillPreviewData | VideoTranscriptSkillPreviewData | undefined {
    return skillPreviewCache.get(taskId);
  }
  
  /**
   * Clear preview data for a task ID
   */
  clearPreviewData(taskId: string): void {
    skillPreviewCache.delete(taskId);
  }
  
  /**
   * Clear all preview data
   */
  clearAllPreviewData(): void {
    skillPreviewCache.clear();
  }
}

// Export singleton instance
export const skillPreviewService = new SkillPreviewService();

