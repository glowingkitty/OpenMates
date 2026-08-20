/**
 * Remotion bundle entry point for deterministic OpenMates browser tutorials.
 *
 * This package is repository tooling and does not share the product video
 * generation backend or accept model-generated composition source.
 */

import {registerRoot} from 'remotion';

import {RemotionRoot} from './Root';

registerRoot(RemotionRoot);
