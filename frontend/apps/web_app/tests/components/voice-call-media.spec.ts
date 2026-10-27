// playwright-account: not_required reason=isolated_component_preview
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
import type { Page } from '@playwright/test';

const preview = (variant: string, width: number) => `/dev/preview/voicecall/VoiceCallMediaPreview?${new URLSearchParams({chrome:'0',theme:'light',background:'#dbeafe',width:String(width),variant})}`;

async function expectCompactMediaControls(page: Page) {
  const panel = page.getByTestId('voice-call-media');
  const counter = panel.locator('.media-navigation > span');
  await expect(counter).toHaveCSS('white-space','nowrap');
  const counterGeometry = await counter.evaluate(element => {
    const bounds = element.getBoundingClientRect();
    return {height:bounds.height,lineHeight:Number.parseFloat(getComputedStyle(element).lineHeight),clipped:element.scrollWidth>element.clientWidth};
  });
  expect(counterGeometry.height).toBeLessThanOrEqual(counterGeometry.lineHeight + 0.5);
  expect(counterGeometry.clipped).toBe(false);
  const controlIds = ['voice-call-media-previous','voice-call-media-next','voice-call-media-expand','voice-call-camera-flip'];
  for (const id of controlIds) {
    const control = page.getByTestId(id);
    const geometry = await control.evaluate(element => {
      const bounds = element.getBoundingClientRect();
      return {width:bounds.width,height:bounds.height,expectedSize:Number.parseFloat(getComputedStyle(document.documentElement).fontSize)*2.5};
    });
    expect(geometry.width).toBeCloseTo(geometry.expectedSize,0);
    expect(geometry.height).toBeCloseTo(geometry.expectedSize,0);
    await expect(control).toHaveCSS('margin-right','0px');
    await expect(control).toHaveCSS('filter','none');
  }
  const [next,collapse,camera,previous] = await Promise.all([
    page.getByTestId('voice-call-media-next').boundingBox(),
    page.getByTestId('voice-call-media-expand').boundingBox(),
    page.getByTestId('voice-call-camera-preview').boundingBox(),
    page.getByTestId('voice-call-media-previous').boundingBox(),
  ]);
  expect(next!.x + next!.width).toBeLessThanOrEqual(collapse!.x);
  expect(camera!.x + camera!.width).toBeLessThanOrEqual(previous!.x);
}

for (const width of [390,1280]) {
  // contract-test: direct surface=gui.web assertions=video-call.video.input-and-output,video-call.video.generated-media-stage,video-call.chat.call-strip-layout
  test(`generated call media retains the camera and navigates plain image/video results at ${width}px`, async ({page}) => {
    await page.setViewportSize({width,height:844});
    await page.goto(preview('generatedWithCamera',width));
    await waitForComponentPreview(page);
    const panel = page.getByTestId('voice-call-media');
    const camera = page.getByTestId('voice-call-camera-preview');
    await expect(panel).toBeVisible();
    await expect(page.getByTestId('voice-call-generated-image')).toBeVisible();
    await expect.poll(() => page.getByTestId('voice-call-generated-image').evaluate(element => (element as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
    await expect(camera).toBeVisible();
    await expect.poll(() => camera.locator('video').evaluate(element => (element as HTMLVideoElement).srcObject instanceof MediaStream)).toBe(true);
    await expect(camera.locator('video')).toHaveCSS('object-fit','contain');
    await expect(page.getByTestId('voice-call-media-ai')).toBeVisible();
    await expect(page.getByTestId('voice-call-media-ai')).toHaveAccessibleName('AI-generated');
    await expect(page.getByTestId('voice-call-media-ai').locator('.ai-icon')).toBeVisible();
    expect(await page.getByTestId('voice-call-media-ai').locator('.ai-icon').evaluate(element => getComputedStyle(element).maskImage)).not.toBe('none');
    // Newly generated results must have their AI marker immediately. Generic
    // app-card icon styles include an 800ms invisible delay, which visibility
    // assertions alone do not catch (Playwright treats opacity:0 as visible).
    expect(await page.getByTestId('voice-call-media-ai').locator('.ai-icon').evaluate(element => {
      const style=getComputedStyle(element);
      return {opacity:style.opacity,animationName:style.animationName,
        contrasting:style.backgroundColor!==getComputedStyle(element.parentElement!).backgroundColor};
    })).toEqual({opacity:'1',animationName:'none',contrasting:true});
    const previous = page.getByTestId('voice-call-media-previous');
    const next = page.getByTestId('voice-call-media-next');
    await expect(previous).toBeDisabled();
    await expect(panel.locator('.media-navigation > span')).toHaveText('1 / 2');
    await expectCompactMediaControls(page);
    await next.hover();
    await expectCompactMediaControls(page);
    await next.focus();
    await expect(next).toBeFocused();
    await page.keyboard.press('Enter');
    const video = page.getByTestId('voice-call-generated-video');
    await expect(video).toBeVisible();
    await expect(video).toHaveAttribute('autoplay','');
    await expect(video).toHaveAttribute('controls','');
    expect(await video.evaluate(element => (element as HTMLVideoElement).muted)).toBe(true);
    expect(await video.evaluate(element => (element as HTMLVideoElement).loop)).toBe(false);
    await expect(next).toBeDisabled();
    await expect(panel.locator('.media-navigation > span')).toHaveText('2 / 2');
    await expect(camera).toBeVisible();
    await expect.poll(() => camera.locator('video').evaluate(element => (element as HTMLVideoElement).readyState)).toBeGreaterThan(1);
    const collapse = page.getByTestId('voice-call-media-expand');
    await collapse.click();
    await expect(panel).toHaveAttribute('data-expanded','false');
    await expect(video).toBeVisible();
    await expect(camera).toBeVisible();
    await expect(collapse).toHaveAccessibleName('Expand');
    await expectCompactMediaControls(page);
    await collapse.click();
    await expect(panel).toHaveAttribute('data-expanded','true');
    await previous.click();
    await expect(page.getByTestId('voice-call-generated-image')).toBeVisible();
    await page.getByTestId('voice-call-show-camera').click();
    await expect(page.getByTestId('voice-call-generated-image')).toHaveCount(0);
    await expect(page.getByTestId('voice-call-media-ai')).toHaveCount(0);
    await expect(camera).toBeVisible();
    const flip = page.getByTestId('voice-call-camera-flip');
    await flip.click();
    await expect(camera.locator('video')).toHaveClass(/mirror/);
    const box = await panel.boundingBox();
    const controlBox = await collapse.boundingBox();
    expect(controlBox!.x + controlBox!.width).toBeLessThanOrEqual(box!.x + box!.width);
    expect(controlBox!.y + controlBox!.height).toBeLessThanOrEqual(box!.y + box!.height);
    expect(await panel.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true);
  });
}

// contract-test: direct surface=gui.web assertions=video-call.video.input-and-output
test('camera-only view stays visible when collapsed and shows no generated-media badge', async ({page}) => {
  await page.goto(preview('camera',390));
  await waitForComponentPreview(page);
  const camera = page.getByTestId('voice-call-camera-preview');
  await expect(camera).toBeVisible();
  await expect(page.getByTestId('voice-call-media-ai')).toHaveCount(0);
  await page.getByTestId('voice-call-media-expand').click();
  await expect(page.getByTestId('voice-call-media')).toHaveAttribute('data-expanded','false');
  await expect(camera).toBeVisible();
});

// contract-test: direct surface=gui.web assertions=video-call.video.input-and-output,video-call.audio.single-owner
test('native camera preview stays attached across real parent call state and timer updates', async ({page}) => {
  await page.setViewportSize({width:390,height:844});
  await page.addInitScript(() => {
    const counts={attached:0,cleared:0,played:0};
    Object.assign(window,{__callPreviewBindings:counts});
    const descriptor=Object.getOwnPropertyDescriptor(HTMLMediaElement.prototype,'srcObject');
    if(!descriptor?.get||!descriptor.set)throw new Error('Native camera stream binding is unavailable');
    Object.defineProperty(HTMLMediaElement.prototype,'srcObject',{
      ...descriptor,
      set(this:HTMLMediaElement,value:HTMLMediaElement['srcObject']) {
        if(this.closest('[data-testid="voice-call-camera-preview"]')) {
          if(value)counts.attached++;else counts.cleared++;
        }
        descriptor.set!.call(this,value);
      },
    });
    const play=HTMLMediaElement.prototype.play;
    HTMLMediaElement.prototype.play=function(this:HTMLMediaElement) {
      if(this.closest('[data-testid="voice-call-camera-preview"]'))counts.played++;
      return play.call(this);
    };
  });
  const query=new URLSearchParams({chrome:'0',theme:'light',background:'#dbeafe',width:'390',props:JSON.stringify({realAudio:false})});
  await page.goto(`/dev/preview/voicecall/VoiceCallBarPreview?${query}`);
  await waitForComponentPreview(page);
  const camera=page.getByTestId('voice-call-video');
  await camera.click();
  const video=page.getByTestId('voice-call-camera-preview').locator('video');
  await expect.poll(()=>video.evaluate((element:HTMLVideoElement)=>element.srcObject instanceof MediaStream&&element.srcObject.active&&element.readyState>=2)).toBe(true);
  const bindings=()=>page.evaluate(()=>(window as unknown as {__callPreviewBindings:{attached:number;cleared:number;played:number}}).__callPreviewBindings);
  const original=await bindings();
  expect(original).toEqual({attached:1,cleared:0,played:1});
  for(let index=0;index<3;index++) {
    await page.getByTestId('voice-call-mute').click();
    await page.getByTestId('voice-call-camera-flip').click();
  }
  // The fixture's real controller replaces its whole store state on these
  // actions and on the native two-second camera-collapse timer.
  await expect(page.getByTestId('voice-call-media')).toHaveAttribute('data-expanded','false');
  expect(await bindings()).toEqual(original);
  await expect.poll(()=>video.evaluate((element:HTMLVideoElement)=>element.srcObject instanceof MediaStream&&element.srcObject.active&&element.readyState>=2)).toBe(true);
  await camera.click();
  await expect(video).toHaveCount(0);
  expect((await bindings()).cleared).toBeGreaterThan(original.cleared);
});

// contract-test: direct surface=gui.web assertions=video-call.video.input-and-output
test('camera errors use regular notifications while collapsed phone camera controls stay clickable', async ({page}) => {
  await page.setViewportSize({width:390,height:844});
  await page.goto(preview('error',390));
  await waitForComponentPreview(page);
  const alert = page.getByTestId('notification').filter({hasText:'Camera access was denied.'});
  await expect(page.locator('.media-error')).toHaveCount(0);
  const panel = page.getByTestId('voice-call-media');
  const expand = page.getByTestId('voice-call-media-expand');
  const flip = page.getByTestId('voice-call-camera-flip');
  const camera = page.getByTestId('voice-call-camera-preview').locator('video');
  await expect(alert).toContainText('Camera access was denied.');
  await expand.click();
  await expect(panel).toHaveAttribute('data-expanded','false');
  const collapsedHeight = await page.evaluate(() => Number.parseFloat(getComputedStyle(document.documentElement).fontSize) * 6);
  await expect.poll(async () => (await panel.boundingBox())!.height).toBeCloseTo(collapsedHeight,0);
  await expect(alert).toBeVisible();
  await flip.hover();
  await flip.click();
  await expect(camera).toHaveClass(/mirror/);
  await expect(alert).toBeVisible();
  await flip.click();
  await expect(camera).not.toHaveClass(/mirror/);
  await expand.hover();
  await expand.click();
  await expect(panel).toHaveAttribute('data-expanded','true');
  await expect(alert).toBeVisible();
});
