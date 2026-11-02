import {main} from './essential-session.mjs';
main('session.foreground-completion-recovery.v1').catch(()=>{console.error('npm essential foreground recovery conformance failed');process.exitCode=1;});
