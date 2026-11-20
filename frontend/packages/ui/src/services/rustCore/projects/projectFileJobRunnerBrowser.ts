/**
 * Browser wiring of the Project file job runner: the shared Worker's
 * `projectFileJobs` unit plus the web stores (approval prompts, privacy inputs).
 */
import { get } from 'svelte/store';
import {
	recordProjectFileChange, requestProjectIgnoredReadApproval, requestProjectWriteApproval
} from '../../../stores/projectFileApprovalStore';
import { personalDataStore } from '../../../stores/personalDataStore';
import { broadcastProjectFilesChanged } from '../../projectBrowserEvents';
import { retainedPreparedPrivacyMemories } from '../../preparedPrivacyForSend';
import { chatPiiMappings } from '../memory/memoryPrivacy';
import {
	decideProjectFileJob, setProjectFileJobMappings, setProjectFileJobPrivacy, stepProjectFileJob
} from './projectFileJobsClient';
import { createProjectFileJobRunner, type ProjectFileJobRunnerDeps } from './projectFileJobRunner';

export function createBrowserProjectFileJobRunner(options: {
	transport: { send: ProjectFileJobRunnerDeps['send'] };
	isActiveChat: (chatId: string) => boolean;
}) {
	return createProjectFileJobRunner({
		send: options.transport.send,
		isActiveChat: options.isActiveChat,
		step: stepProjectFileJob,
		decide: decideProjectFileJob,
		setMappings: setProjectFileJobMappings,
		setPrivacy: setProjectFileJobPrivacy,
		chatMappings: chatPiiMappings,
		privacyMemories: retainedPreparedPrivacyMemories,
		privacyEnabled: () => get(personalDataStore.settings).masterEnabled,
		storage: localStorage,
		requestWrite: requestProjectWriteApproval,
		requestRead: requestProjectIgnoredReadApproval,
		onApplied: recordProjectFileChange,
		onFilesChanged: broadcastProjectFilesChanged
	});
}
