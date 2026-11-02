import {main} from './essential-session.mjs';
main('session.chat-change-monitor.v1').catch(()=>{console.error('npm essential monitor conformance failed');process.exitCode=1;});
