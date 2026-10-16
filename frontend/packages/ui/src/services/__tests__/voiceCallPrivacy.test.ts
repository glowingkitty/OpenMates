import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
const dialog = vi.hoisted(() => ({ mount:vi.fn(), unmount:vi.fn(async()=>{}) }));
vi.mock('svelte',()=>({mount:dialog.mount,unmount:dialog.unmount}));
vi.mock('../../components/voicecall/VoiceCallPrivacyDialog.svelte',()=>({default:{}}));
vi.mock('../../config/api',()=>({getApiUrl:()=> 'https://first-party.invalid'}));
import { ensureVoiceCallPrivacyAcknowledgement } from '../voiceCallPrivacy';
const absent = {version:1,acknowledged:false,acknowledged_at:null};
const saved = {version:1,acknowledged:true,acknowledged_at:1700000000};
const response = (value:unknown,ok=true)=>({ok,json:async()=>value});
const options = () => dialog.mount.mock.calls[0][1] as {props:{onContinue:()=>Promise<void>;onCancel:()=>void}};

describe('first-call server-profile acknowledgement',()=>{
  let fetcher: ReturnType<typeof vi.fn>;
  beforeEach(()=>{
    fetcher=vi.fn();vi.stubGlobal('fetch',fetcher);
    dialog.mount.mockReset().mockReturnValue({});dialog.unmount.mockClear();
  });
  afterEach(()=>vi.unstubAllGlobals());

  // contract-test: direct surface=gui.web assertions=video-call.privacy.first-call-warning
  it('checks the authoritative profile anew across launches without repeating a saved warning',async()=>{
    fetcher.mockResolvedValue(response(saved));
    for(let launch=0;launch<2;launch++)expect(await ensureVoiceCallPrivacyAcknowledgement(new AbortController().signal,()=>{})).toBe(true);
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(fetcher.mock.calls.every(call=>call[1].method==='GET'&&call[1].credentials==='include')).toBe(true);
    expect(dialog.mount).not.toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=video-call.privacy.first-call-warning
  it('does not save on warning display or Cancel',async()=>{
    fetcher.mockResolvedValueOnce(response(absent));
    const pending=ensureVoiceCallPrivacyAcknowledgement(new AbortController().signal,()=>{});
    await vi.waitFor(()=>expect(dialog.mount).toHaveBeenCalledOnce());
    expect(fetcher).toHaveBeenCalledOnce();
    options().props.onCancel();
    expect(await pending).toBe(false);
    expect(fetcher.mock.calls.some(call=>call[1].method==='POST')).toBe(false);
    expect(dialog.unmount).toHaveBeenCalledOnce();
  });

  // contract-test: direct surface=gui.web assertions=video-call.privacy.first-call-warning
  it('saves only Continue with server version and resumes only after successful persistence',async()=>{
    let complete!: (result:unknown)=>void;
    fetcher.mockResolvedValueOnce(response(absent)).mockImplementationOnce(()=>new Promise(resolve=>{complete=resolve;}));
    const gesture=vi.fn();let resumed=false;
    const pending=ensureVoiceCallPrivacyAcknowledgement(new AbortController().signal,gesture).then(value=>{resumed=value;return value;});
    await vi.waitFor(()=>expect(dialog.mount).toHaveBeenCalledOnce());
    const saving=options().props.onContinue();
    expect(gesture).toHaveBeenCalledOnce();
    expect(fetcher.mock.calls[1]).toEqual(['https://first-party.invalid/v1/settings/voice-google-processing-ack',expect.objectContaining({method:'POST',credentials:'include',body:'{"version":1}'})]);
    expect(resumed).toBe(false);
    complete(response(saved));await saving;
    expect(await pending).toBe(true);
  });

  // contract-test: direct surface=gui.web assertions=video-call.privacy.first-call-warning
  it('leaves a failed save blocked and permits an explicit retry',async()=>{
    fetcher.mockResolvedValueOnce(response(absent)).mockResolvedValueOnce(response({},false)).mockResolvedValueOnce(response(saved));
    const pending=ensureVoiceCallPrivacyAcknowledgement(new AbortController().signal,()=>{});
    await vi.waitFor(()=>expect(dialog.mount).toHaveBeenCalledOnce());
    await expect(options().props.onContinue()).rejects.toThrow();
    expect(dialog.unmount).not.toHaveBeenCalled();
    await options().props.onContinue();expect(await pending).toBe(true);
  });

  // contract-test: direct surface=gui.web assertions=video-call.privacy.first-call-warning
  it('aborts an open warning without saving and ignores late Continue',async()=>{
    fetcher.mockResolvedValueOnce(response(absent));
    const abort=new AbortController();const pending=ensureVoiceCallPrivacyAcknowledgement(abort.signal,()=>{});
    await vi.waitFor(()=>expect(dialog.mount).toHaveBeenCalledOnce());
    abort.abort();expect(await pending).toBe(false);
    await options().props.onContinue();expect(fetcher).toHaveBeenCalledOnce();
    expect(dialog.unmount).toHaveBeenCalledOnce();
  });

  // contract-test: direct surface=gui.web assertions=video-call.privacy.first-call-warning
  it('rejects unavailable or malformed server acknowledgement instead of a local bypass',async()=>{
    for(const value of [response({},false),response({...saved,version:2}),response({...saved,acknowledged_at:null})]){
      fetcher.mockResolvedValueOnce(value);
      await expect(ensureVoiceCallPrivacyAcknowledgement(new AbortController().signal,()=>{})).rejects.toThrow();
    }
    expect(dialog.mount).not.toHaveBeenCalled();
  });
});
