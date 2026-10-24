import {expect,test} from '../helpers/cookie-audit';
import {waitForComponentPreview} from '../helpers/component-preview';
import type {Page,Locator} from '@playwright/test';

// playwright-account: not_required reason=isolated_component_preview
async function open(page: Page, component: string, variant='', width=390, theme='light') {
  await page.setViewportSize({width,height:width<600?844:950});
  await page.goto(`/dev/preview/embeds/business/${component}?theme=${theme}&background=%23dbeafe&width=${width}&chrome=0${variant?'&variant='+variant:''}`);
  await waitForComponentPreview(page);
}
async function fits(page:Page, element:Locator) {
  await expect(element).toBeVisible();
  const box=await element.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.x).toBeGreaterThanOrEqual(-1);
  expect(box!.x+box!.width).toBeLessThanOrEqual(page.viewportSize()!.width+1);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(page.viewportSize()!.width+1);
}

// contract-test: direct surface=gui.web assertions=trademarks.coverage,trademarks.parity
test('Apps retains the verified zero-match coverage card',async({page})=>{
  await page.setViewportSize({width:390,height:844});
  await page.goto('/dev/preview/apps/AppsInlineResults?variant=trademarkEmpty&chrome=0');
  await waitForComponentPreview(page);
  const root=page.getByTestId('apps-inline-results-grid');
  await expect(root.getByTestId('embed-preview')).toHaveCount(1);
  await expect(root).toContainText('Records: 0');
  await expect(root).toContainText('US · Checked');
  await expect(page.getByTestId('apps-inline-results')).not.toContainText('No results found.');
});

// contract-test: direct surface=gui.web assertions=trademarks.coverage,trademarks.evidence,trademarks.parity
test('Apps fullscreen keeps unsupported-region evidence and manual links',async({page})=>{
  await page.setViewportSize({width:390,height:844});
  await page.goto('/dev/preview/apps/AppsResultFullscreen?variant=trademarkGap&chrome=0');
  await waitForComponentPreview(page);
  const root=page.getByTestId('trademark-search-fullscreen');
  await expect(root).toBeVisible();
  await expect(root.getByTestId('trademark-error')).toContainText('No requested region');
  await expect(root.getByTestId('trademark-search-coverage')).toContainText('DE');
  await expect(root.getByTestId('trademark-search-coverage').getByRole('link')).toHaveAttribute('href',/^https:\/\/register\.dpma\.de\//);
  await expect(root.getByTestId('trademark-empty')).toHaveCount(0);
});

// contract-test: direct surface=gui.web assertions=trademarks.coverage,trademarks.parity
test('preview preserves coverage, terminal states and phone layout',async({page},testInfo)=>{
  test.setTimeout(90_000);
  const root=page.locator('.unified-embed-preview').first();
  await open(page,'BusinessTrademarkSearchEmbedPreview');
  await fits(page,root);
  await expect(root).toContainText('ADIDAS');
  await expect(root).toContainText('ExampleTrademarks');
  await expect(root).toContainText('DE · Not searched');
  await expect(root).toContainText('Preliminary search');
  await expect(root.locator('.icon_rounded.business').first()).toBeVisible();
  await testInfo.attach('trademark-preview-phone-light',{body:await root.screenshot(),contentType:'image/png'});
  for(const variant of ['processing','cancelled','error','empty','long']){
    await open(page,'BusinessTrademarkSearchEmbedPreview',variant);
    await fits(page,root);
    if(variant==='error') await expect(root).toContainText('Search data unavailable');
    if(variant==='empty') await expect(root).toContainText('Records: 0');
    if(variant==='cancelled') await expect(root).toContainText(/cancelled/i);
  }
  await open(page,'BusinessTrademarkSearchEmbedPreview','',1280,'dark');
  await fits(page,root);
  await testInfo.attach('trademark-preview-laptop-dark',{body:await root.screenshot(),contentType:'image/png'});
});

// contract-test: direct surface=gui.web assertions=trademarks.coverage,trademarks.evidence,trademarks.parity
test('fullscreen retains records, filters, official links and explicit failures',async({page},testInfo)=>{
  test.setTimeout(90_000);
  const root=page.getByTestId('trademark-search-fullscreen');
  await open(page,'BusinessTrademarkSearchEmbedFullscreen');
  await fits(page,root);
  await expect(page.getByTestId('trademark-search-coverage')).toContainText('DE');
  await expect(page.getByTestId('trademark-search-coverage')).toContainText('Not searched');
  await expect(page.getByTestId('trademark-fullscreen-limitation')).toContainText('legal availability');
  const card=page.getByTestId('trademark-record');
  await fits(page,card);
  await expect(card).toContainText('Registered');
  await expect(card).toContainText('adidas AG');
  await expect(card).toContainText('72318279');
  await card.getByTestId('result-card-title').click();
  const detail = page.getByTestId('trademark-record-fullscreen');
  await expect(detail).toBeVisible();
  await detail.locator('summary').focus();
  await page.keyboard.press('Enter');
  await expect(detail).toContainText('Tote bags.');
  await expect(detail.getByTestId('trademark-record-source')).toHaveAttribute('href',/^https:\/\/tsdr\.ExampleTrademarks\.gov\/#caseNumber=72318279/);
  await testInfo.attach('trademark-fullscreen-phone-light',{body:await root.screenshot(),contentType:'image/png'});
  await open(page,'BusinessTrademarkSearchEmbedFullscreen','filters',1280,'dark');
  await fits(page,root);
  await page.getByTestId('search-template-filter-button').click();
  await expect(page.getByTestId('trademark-search-filters')).toContainText('9, 42');
  await expect(page.getByTestId('trademark-search-filters')).toContainText('Similar spelling');
  await expect(page.getByTestId('trademark-search-filters')).toContainText('All statuses');
  await testInfo.attach('trademark-fullscreen-laptop-dark',{body:await root.screenshot(),contentType:'image/png'});
  await open(page,'BusinessTrademarkSearchEmbedFullscreen','empty');
  await expect(page.getByTestId('trademark-empty')).toBeVisible();
  await expect(page.getByTestId('trademark-record')).toHaveCount(0);
  await open(page,'BusinessTrademarkSearchEmbedFullscreen','error');
  await expect(page.getByTestId('trademark-error')).toBeVisible();
  await expect(page.getByTestId('trademark-empty')).toHaveCount(0);
  await open(page,'BusinessTrademarkSearchEmbedFullscreen','unsafeLink');
  await page.getByTestId('trademark-record').getByTestId('result-card-title').click();
  await expect(page.getByTestId('trademark-record-fullscreen')).toBeVisible();
  await expect(page.getByTestId('trademark-record-source')).toHaveCount(0);
  await open(page,'BusinessTrademarkSearchEmbedFullscreen','long');
  await page.getByTestId('trademark-record').getByTestId('result-card-title').click();
  await page.getByTestId('trademark-record-fullscreen').locator('summary').click();
  await fits(page,page.getByTestId('trademark-record-fullscreen'));
});
