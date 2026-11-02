import {LegacyProducerLifetime} from './legacyProducerLifetime';
/** Original realm owner shared by actual annotation sender and DB mutators. */
export const legacyHighlightProducer=new LegacyProducerLifetime('message-highlights');
