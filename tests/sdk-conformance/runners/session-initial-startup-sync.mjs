import {main} from './essential-session.mjs';
main('session.initial-startup-sync.v1').catch(()=>{console.error('npm initial startup conformance failed');process.exitCode=1;});
