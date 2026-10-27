// playwright-account: not_required reason=isolated_component_preview
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

const preview = (variant: string | undefined, width:number, fixed:boolean, realAudio?:boolean) =>
  `/dev/preview/voicecall/VoiceCallBarPreview?${new URLSearchParams({chrome:'0',theme:'light',background:'#dbeafe',width:String(width),props:JSON.stringify({fixed,...(realAudio===undefined?{}:{realAudio})}),...(variant?{variant}:{})})}`;
const globalPreview = (width:number, variant?:string) =>
  `/dev/preview/voicecall/VoiceCallGlobalHeaderPreview?${new URLSearchParams({chrome:'0',theme:'light',background:'#dbeafe',width:String(width),...(variant?{variant}:{})})}`;

test.describe('Reference voice call strip', () => {
  for(const width of [390,1280]) {
    // contract-test: direct surface=gui.web assertions=video-call.video.generated-media-stage,video-call.chat.call-strip-layout,video-call.video.input-and-output
    test(`expanded media fits the real chat history when its available height changes at ${width}px`,async({page})=>{
      await page.setViewportSize({width,height:900});
      await page.goto(preview('constrainedMedia',width,false,false));
      await waitForComponentPreview(page);
      const history=page.getByTestId('chat-history-container');
      const fixture=page.getByTestId('voice-call-history-fixture');
      const stage=page.getByTestId('voice-call-media');
      const expand=page.getByTestId('voice-call-media-expand');
      const camera=page.getByTestId('voice-call-video');
      const expectControlsInside=async()=>{
        await expect.poll(()=>history.evaluate(root=>{
          const bounds=root.getBoundingClientRect();
          const ids=['voice-call-video','voice-call-mute','voice-call-hangup','voice-call-media-ai','voice-call-media-expand','voice-call-camera-flip'];
          return ids.every(id=>{
            const control=root.querySelector<HTMLElement>(`[data-testid="${id}"]`);
            if(!control)return id==='voice-call-camera-flip';
            const box=control.getBoundingClientRect();
            return box.width>0&&box.height>0&&box.left>=bounds.left-.5&&box.right<=bounds.right+.5&&box.top>=bounds.top-.5&&box.bottom<=bounds.bottom+.5;
          });
        }),{message:'toolbar, AI badge and media controls fit the actual chat scrollport'}).toBe(true);
        for(const id of ['voice-call-video','voice-call-mute','voice-call-hangup','voice-call-media-ai','voice-call-media-expand']) {
          await expect(page.getByTestId(id)).toBeInViewport({ratio:1});
        }
      };
      await expect(stage).toHaveAttribute('data-expanded','true');
      await history.evaluate(root=>{root.scrollTop=root.scrollHeight;});
      await expect.poll(()=>history.evaluate(root=>root.scrollTop)).toBeGreaterThan(0);
      await expectControlsInside();
      await camera.click();
      const cameraVideo=page.getByTestId('voice-call-camera-preview').locator('video');
      await expect.poll(()=>cameraVideo.evaluate((video:HTMLVideoElement)=>video.srcObject instanceof MediaStream&&video.readyState>=2)).toBe(true);
      await expect(stage).toHaveAttribute('data-expanded','false');
      const collapsedHeight=await page.evaluate(()=>Number.parseFloat(getComputedStyle(document.documentElement).fontSize)*6);
      await expect.poll(async()=>(await stage.boundingBox())!.height).toBeCloseTo(collapsedHeight,0);
      await expand.click();
      await expect(stage).toHaveAttribute('data-expanded','true');
      await expectControlsInside();
      await expect(page.getByTestId('voice-call-camera-flip')).toBeInViewport({ratio:1});
      await history.evaluate(root=>{root.scrollTop=root.scrollHeight;});
      await expect.poll(()=>history.evaluate(root=>root.scrollTop)).toBeGreaterThan(0);
      await expectControlsInside();
      const originalHeight=(await stage.boundingBox())!.height;
      await fixture.evaluate(element=>{element.style.height='280px';});
      await expect.poll(async()=>(await stage.boundingBox())!.height).toBeLessThan(originalHeight);
      await expectControlsInside();
      await expect(page.getByTestId('voice-call-camera-flip')).toBeInViewport({ratio:1});
      await page.getByTestId('voice-call-camera-flip').hover();
      await page.getByTestId('voice-call-camera-flip').click();
      await expect(cameraVideo).toHaveClass(/mirror/);
      await expand.click();
      await expect(stage).toHaveAttribute('data-expanded','false');
      await expect.poll(async()=>(await stage.boundingBox())!.height).toBeCloseTo(collapsedHeight,0);
    });
  }
  // contract-test: direct surface=gui.web assertions=video-call.chat.launch-and-provider,video-call.chat.call-strip-layout
  test('discloses the provider and usage-based billing in the launch control accessible description',async({page})=>{
    await page.goto('/dev/preview/voicecall/VoiceCallHeaderActions?chrome=0&theme=light&background=%23dbeafe&width=390');
    await waitForComponentPreview(page);
    const launch=page.getByTestId('voice-call-start');
    await expect(launch).toHaveAccessibleName('Start voice call');
    await expect(launch).toHaveAccessibleDescription('Voice calls use Mistral transcription, ElevenLabs v4 Turbo voice, normal OpenMates AI routing and usage-based billing.');
  });
  // contract-test: direct surface=gui.web assertions=video-call.chat.call-strip-layout,video-call.chat.activity-status,video-call.audio.single-owner
  test('dedicated microphone overlay toggles mute while the call remains live at 320px RTL',async({page},testInfo)=>{
    await page.setViewportSize({width:320,height:844});
    await page.goto(preview(undefined,320,true,false));
    await waitForComponentPreview(page);
    await page.locator('html').evaluate(element=>element.setAttribute('dir','rtl'));
    const bar=page.getByTestId('voice-call-bar');
    const mute=page.getByTestId('voice-call-mute');
    const wave=page.getByTestId('voice-call-waveform');
    const timer=page.getByTestId('voice-call-timer');
    await expect(bar).toBeVisible();
    await expect(mute).toHaveAccessibleName('Mute');
    await expect(mute).toHaveAttribute('aria-pressed','false');
    await expect(wave.locator('span')).toHaveCount(48);
    const [barBox,muteBox,waveBox,timerBox]=await Promise.all([
      bar.boundingBox(),mute.boundingBox(),wave.boundingBox(),timer.boundingBox(),
    ]);
    expect(muteBox!.x).toBeGreaterThanOrEqual(waveBox!.x);
    expect(muteBox!.x+muteBox!.width).toBeLessThanOrEqual(waveBox!.x+waveBox!.width);
    expect(timerBox!.x+timerBox!.width).toBeLessThanOrEqual(waveBox!.x);
    expect(muteBox!.x).toBeGreaterThanOrEqual(barBox!.x);
    expect(muteBox!.x+muteBox!.width).toBeLessThanOrEqual(barBox!.x+barBox!.width);
    expect(await mute.evaluate(element=>{
      const rect=element.getBoundingClientRect();
      const hit=document.elementFromPoint(rect.left+rect.width/2,rect.top+rect.height/2);
      return hit===element||element.contains(hit);
    })).toBe(true);
    await mute.click();
    await expect(mute).toHaveAttribute('aria-pressed','true');
    await expect(mute).toHaveAccessibleName('Unmute');
    await expect(mute.locator('.microphone-slash')).toBeVisible();
    await expect(mute.locator('.icon_recordaudio')).toHaveCSS('background-color','rgb(255, 85, 59)');
    await expect(mute).toHaveAttribute('data-activity-active','false');
    await expect(page.getByTestId('voice-call-status-text')).toHaveText('Microphone muted');
    await expect(bar).toBeVisible();
    await expect(timer).toHaveText('00:15');
    await page.screenshot({path:testInfo.outputPath('voice-call-microphone-muted-rtl-320.png')});
    await mute.click();
    await expect(mute).toHaveAttribute('aria-pressed','false');
    await expect(mute.locator('.microphone-slash')).toHaveCount(0);
    await expect(page.getByTestId('voice-call-status-text')).toHaveText('Listening · You can speak now');
    await expect(bar).toBeVisible();
  });
  for (const width of [390,1280]) {
    for (const fixed of [false,true]) {
      for (const {variant, active, muted, waveform, status} of [
        {variant:undefined,active:true,muted:false,waveform:true,status:'Listening · You can speak now'},
        {variant:'idle',active:false,muted:false,waveform:false,status:'Speak to resume call.'},
        {variant:'muted',active:false,muted:true,waveform:false,status:'Microphone muted'},
        {variant:'mutedWorking',active:true,muted:true,waveform:false,status:'OpenMates is working…'},
        {variant:'playback',active:false,muted:true,waveform:true,status:'OpenMates is speaking…'},
      ]) {
        // contract-test: direct surface=gui.web assertions=video-call.chat.call-strip-layout,video-call.chat.activity-status,video-call.audio.single-owner
        test(`${fixed?'fixed':'inline'} ${variant??'active'} strip at ${width}px matches the reference and keeps accessible controls`, async ({page}) => {
          await page.setViewportSize({width,height:844});
          await page.emulateMedia({reducedMotion:'reduce'});
          await page.goto(preview(variant,width,fixed));
          await waitForComponentPreview(page);
          const bar=page.getByTestId('voice-call-bar');
          const center=page.getByTestId('voice-call-mute');
          await expect(bar).toBeVisible();
          await expect(bar).toHaveCSS('background-image',/linear-gradient/);
          await expect(bar).toHaveCSS('color','rgb(255, 255, 255)');
          await expect(page.getByTestId('voice-call-timer')).toHaveText('00:15');
          await expect(center).toHaveAttribute('data-activity-active',String(active));
          await expect(page.getByTestId('voice-call-timer')).toHaveCSS('opacity',active?'1':'0.48');
          await expect(center).toHaveAttribute('aria-pressed',String(muted));
          await expect(center).toHaveAccessibleName(muted?'Unmute':'Mute');
          await expect(center).toHaveClass(/round/);
          await expect(center.locator('.icon_recordaudio')).not.toHaveCSS('mask-image','none');
          await expect(center.locator('.icon_recordaudio')).toHaveCSS('background-color',muted?'rgb(255, 85, 59)':'rgb(255, 255, 255)');
          if(muted) await expect(center.locator('.microphone-slash')).toBeVisible();
          else await expect(center.locator('.microphone-slash')).toHaveCount(0);
          await expect(page.getByTestId('voice-call-status-text')).toHaveText(status);
          await expect(page.getByTestId('voice-call-status')).toHaveCSS('clip','rect(0px, 0px, 0px, 0px)');
          await expect(page.getByTestId('voice-call-credits')).toHaveCount(0);
          await expect(page.getByTestId('voice-call-pricing')).toHaveCount(0);
          await expect(page.getByTestId('voice-call-return')).toHaveCount(0);
          await expect(bar.getByText('Via Voxtral',{exact:true})).toHaveCount(0);
          await expect(bar.getByText('Voice call',{exact:true})).toHaveCount(0);
          const video=page.getByTestId('voice-call-video');
          const end=page.getByTestId('voice-call-hangup');
          await expect(video).toHaveAccessibleName('Video call');
          await expect(end).toHaveAccessibleName('Hang up');
          await expect(video.locator('.icon_video_call')).not.toHaveCSS('mask-image','none');
          await expect(end.locator('.icon_call')).not.toHaveCSS('mask-image','none');
          await expect(end.locator('.icon_call')).toHaveCSS('color','rgb(255, 85, 59)');
          const [bounds,videoBox,centerBox,endBox,timerBox,waveBox]=await Promise.all([
            bar.boundingBox(),video.boundingBox(),center.boundingBox(),end.boundingBox(),
            page.getByTestId('voice-call-timer').boundingBox(),bar.locator('.wave').boundingBox(),
          ]);
          expect(bounds!.height).toBeGreaterThanOrEqual(60);expect(bounds!.height).toBeLessThanOrEqual(80);
          expect(bounds!.x).toBeGreaterThanOrEqual(0);expect(bounds!.x+bounds!.width).toBeLessThanOrEqual(width+1);
          expect(videoBox!.x+videoBox!.width).toBeLessThanOrEqual(centerBox!.x+1);
          expect(centerBox!.x+centerBox!.width).toBeLessThanOrEqual(endBox!.x+1);
          expect(centerBox!.width).toBe(endBox!.width);
          expect(centerBox!.height).toBe(endBox!.height);
          expect(timerBox!.x+timerBox!.width).toBeLessThanOrEqual(waveBox!.x);
          expect(centerBox!.x).toBeGreaterThanOrEqual(waveBox!.x);
          expect(centerBox!.x+centerBox!.width).toBeLessThanOrEqual(waveBox!.x+waveBox!.width);
          const bars=page.getByTestId('voice-call-waveform').locator('span');
          await expect(bars).toHaveCount(48);
          if(waveform) await expect.poll(()=>bars.evaluateAll(nodes=>nodes.some(node=>Number(node.getAttribute('data-level'))>0))).toBe(true);
          else expect(await bars.evaluateAll(nodes=>nodes.every(node=>Number(node.getAttribute('data-level'))===0))).toBe(true);
          if(fixed) {
            const more=page.getByTestId('voice-call-more');const close=page.getByTestId('voice-call-close-chat');
            await expect(more).toBeVisible();await expect(close).toHaveAccessibleName('Close chat');
            const [moreBox,closeBox]=await Promise.all([more.boundingBox(),close.boundingBox()]);
            expect(moreBox!.x+moreBox!.width).toBeLessThanOrEqual(videoBox!.x+1);
            expect(endBox!.x+endBox!.width).toBeLessThanOrEqual(closeBox!.x+1);
          } else { await expect(page.getByTestId('voice-call-more')).toHaveCount(0);await expect(page.getByTestId('voice-call-close-chat')).toHaveCount(0); }
          await center.focus();await expect(center).toBeFocused();
          await page.keyboard.press('Enter');await expect(center).toHaveAttribute('aria-pressed',String(!muted));
          await expect(bar).toBeVisible();await expect(page.getByTestId('voice-call-timer')).toHaveText('00:15');
          if(!variant) {
            await video.click();await expect(video).toHaveAttribute('aria-pressed','true');
            await expect(page.getByTestId('voice-call-camera-preview')).toBeVisible();
            await expect(page.getByTestId('voice-call-media')).toHaveAttribute('data-expanded','true');
            await expect(page.getByTestId('voice-call-media')).toHaveAttribute('data-expanded','false');
            await page.getByTestId('voice-call-media-expand').click();
            await expect(page.getByTestId('voice-call-media')).toHaveAttribute('data-expanded','true');
            await video.click();await expect(video).toHaveAttribute('aria-pressed','false');
            await expect(page.getByTestId('voice-call-camera-preview')).toHaveCount(0);
          }
          if(fixed && !variant) {
            const more=page.getByTestId('voice-call-more');await more.focus();await page.keyboard.press('Enter');
            const menu=page.getByRole('menu');await expect(menu).toBeVisible();
            const menuBox=await menu.boundingBox();expect(menuBox!.x).toBeGreaterThanOrEqual(0);expect(menuBox!.x+menuBox!.width).toBeLessThanOrEqual(width);
            await page.getByRole('menuitem',{name:'Unmute',exact:true}).click();await expect(center).toHaveAttribute('aria-pressed','false');
            await more.click();await expect(menu).not.toBeVisible();
            await page.getByTestId('voice-call-close-chat').click();await expect(page.getByTestId('preview-chat-closed')).toBeVisible();await expect(bar).toBeVisible();
            const [postCloseBar,postCloseMute,postCloseHangup]=await Promise.all([bar.boundingBox(),center.boundingBox(),end.boundingBox()]);
            expect(postCloseBar!.width).toBe(bounds!.width);
            expect(postCloseMute!.x+postCloseMute!.width).toBeLessThanOrEqual(postCloseHangup!.x);
            expect(await end.evaluate(element=>{
              const rect=element.getBoundingClientRect();
              const hit=document.elementFromPoint(rect.left+rect.width/2,rect.top+rect.height/2);
              return hit===element||element.contains(hit);
            })).toBe(true);
          }
          await end.click();await expect(bar).toHaveCount(0);
        });
      }
    }
    // contract-test: direct surface=gui.web assertions=video-call.chat.call-strip-layout,video-call.chat.fixed-binding,video-call.chat.activity-status
    test(`brand slot pill at ${width}px returns to the active call without covering navigation`, async({page})=>{
      await page.setViewportSize({width,height:844});
      await page.emulateMedia({reducedMotion:'no-preference'});
      await page.addInitScript(()=>window.addEventListener('voice-call-preview-return',()=>Object.assign(window,{__returnedToCall:true})));
      await page.goto(globalPreview(width));await waitForComponentPreview(page);
      const pill=page.getByTestId('voice-call-pill');await expect(pill).toBeVisible();await expect(pill).toHaveAccessibleName('Return to chat');
      await expect(page.getByTestId('voice-call-pill-timer')).toHaveText('00:15');
      await expect(pill).toHaveCSS('animation-name',/voice-call-pulse$/);
      await expect(pill).toHaveCSS('animation-duration','3s');
      await expect(pill).toHaveCSS('animation-iteration-count','infinite');
      await page.emulateMedia({reducedMotion:'reduce'});
      await expect(pill).toHaveCSS('animation-name','none');
      await expect(page.getByTestId('voice-call-bar')).toHaveCount(0);
      const [header,pillBox]=await Promise.all([page.getByTestId('global-header').boundingBox(),pill.boundingBox()]);
      expect(pillBox!.y).toBeGreaterThanOrEqual(header!.y);expect(pillBox!.y+pillBox!.height).toBeLessThanOrEqual(header!.y+header!.height);
      await pill.focus();await page.keyboard.press('Enter');await expect.poll(()=>page.evaluate(()=>(window as unknown as {__returnedToCall?:boolean}).__returnedToCall)).toBe(true);
    });
  }
  for(const variant of ['connecting','error','contextError']) {
    // contract-test: direct surface=gui.web assertions=video-call.chat.call-strip-layout,video-call.lifecycle.recovery-and-billing
    test(`${variant} shows controls only while connecting`,async({page})=>{
      await page.setViewportSize({width:390,height:844});await page.goto(preview(variant,390,false));await waitForComponentPreview(page);
      if(variant==='connecting') {
        await expect(page.getByTestId('voice-call-bar')).toBeVisible();
        await expect(page.getByTestId('voice-call-mute')).toBeDisabled();
        await expect(page.getByTestId('voice-call-connecting')).toBeVisible();
        await expect(page.getByTestId('voice-call-bar')).toHaveAttribute('aria-busy','true');
        await page.getByTestId('voice-call-hangup').click();
      }
      await expect(page.getByTestId('voice-call-bar')).toHaveCount(0);
      await expect(page.getByTestId('voice-call-error')).toHaveCount(0);
    });
  }
});
