import {LegacyProducerLifetime} from './legacyProducerLifetime';
/** Fixed production owners shared by the actual optimistic/editor and database
 * entry points. Callers cannot replace the participant set at cutover. */
export const legacyEditorProducer=new LegacyProducerLifetime('legacyEditorProducer');
export const legacyDatabasePreparationProducer=new LegacyProducerLifetime('legacyDatabasePreparationProducer');
