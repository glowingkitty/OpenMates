/* eslint-disable @typescript-eslint/no-require-imports */
/** Real terminal frames without video capture. Runner-private HOME and CLI state belong to the caller. */
export {};
const { spawn } = require('node:child_process');

type Step = { text?: string; key?: string; waitFor: string; absent?: string[] };
const driver = String.raw`
import errno,fcntl,json,os,pty,re,select,struct,subprocess,sys,termios,time
plan=json.loads(sys.argv[1]); master,slave=pty.openpty()
fcntl.ioctl(slave,termios.TIOCSWINSZ,struct.pack('HHHH',32,100,0,0))
child=subprocess.Popen(['node',plan['cli']],stdin=slave,stdout=slave,stderr=slave,start_new_session=True)
os.close(slave); output=''; latest_frame=''; checkpoints=[]
def read_frame():
    global output,latest_frame
    if select.select([master],[],[],0.05)[0]:
        try: output+=os.read(master,65536).decode('utf8',errors='replace')
        except OSError as exc:
            if exc.errno!=errno.EIO: raise
    # TuiTerminal.render writes complete viewports between synchronized-output
    # markers, addressing each row explicitly. Retain the last complete frame
    # while the next write is partial; old screens must never satisfy a step.
    start_marker='\x1b[?2026h'; end_marker='\x1b[?2026l'
    while True:
        start=output.find(start_marker)
        end=output.find(end_marker,start+len(start_marker)) if start>=0 else -1
        if end<0: break
        latest_frame=output[start+len(start_marker):end]
        output=output[end+len(end_marker):]
    frame=re.sub(r'\x1b\[\d+;1H','\n',latest_frame)
    return re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]','',frame).replace('\r','')
keys={'skip':'n','enter':'\r','exit':'\x03','sidebar':'\x02','escape':'\x1b'}
try:
    for step in plan['steps']:
        if step.get('text') is not None: os.write(master,step['text'].encode()+b'\r')
        if step.get('key'): os.write(master,keys[step['key']].encode())
        deadline=time.monotonic()+60
        while True:
            frame=read_frame()
            if step['waitFor'] in frame and not any(value in frame for value in step.get('absent',[])):
                checkpoints.append(frame); break
            if child.poll() is not None or time.monotonic()>deadline:
                raise RuntimeError('TUI frame did not contain '+step['waitFor']+'; last frame: '+frame[-3000:])
    os.write(master,b'\x03'); child.wait(timeout=10)
    print(json.dumps({'frames':checkpoints,'code':child.returncode}))
finally:
    if child.poll() is None: child.kill();child.wait()
    os.close(master)
`;

function runTuiPty(cli: string, env: Record<string, string | undefined>, steps: Step[]): Promise<{ frames: string[]; code: number }> {
  return new Promise((resolve, reject) => {
    const child = spawn('python3', ['-c', driver, JSON.stringify({cli, steps})], {env, stdio: ['ignore', 'pipe', 'pipe']});
    let stdout = '', stderr = '';
    child.stdout.on('data', (chunk: Buffer) => { stdout += chunk.toString(); });
    child.stderr.on('data', (chunk: Buffer) => { stderr += chunk.toString(); });
    child.once('error', reject);
    child.once('close', (code: number | null) => {
      if (code !== 0) reject(new Error('Terminal check failed: ' + stderr));
      else { try { resolve(JSON.parse(stdout)); } catch (error) { reject(error); } }
    });
  });
}
module.exports = { runTuiPty };
