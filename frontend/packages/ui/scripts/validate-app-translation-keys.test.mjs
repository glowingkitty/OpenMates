import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdtempSync, mkdirSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import {
    collectDeclaredFocusInstructionKeys,
    collectMetadataKeyRefs,
    resolvesToText,
    scanStaticKeyRefs,
    validateAppTranslationKeys,
} from './validate-app-translation-keys.js';

const LANGS = ['en', 'de', 'fr'];
const t = text => ({ text });

/** Locale fixture where find_brand_name is complete and price_products only exists in English. */
function locales({ priceProductsEn = true } = {}) {
    const base = lang => ({
        app_focus_modes: {
            business: {
                find_brand_name: { ...t(`Brand ${lang}`), description: t(`Brand desc ${lang}`) },
            },
        },
        app_skills: { business: { company_financials: { ...t('Financials'), description: t('SEC data') } } },
    });
    const en = base('en');
    if (priceProductsEn) en.app_focus_modes.business.price_products = { ...t('Price your products'), description: t('Work out prices') };
    return { en, de: base('de'), fr: base('fr') };
}

const metadata = {
    business: {
        skills: [{ id: 'company_financials', name_translation_key: 'app_skills.business.company_financials', description_translation_key: 'app_skills.business.company_financials.description' }],
        focus_modes: [
            { id: 'find_brand_name', name_translation_key: 'app_focus_modes.business.find_brand_name', description_translation_key: 'app_focus_modes.business.find_brand_name.description' },
            { id: 'price_products', name_translation_key: 'app_focus_modes.business.price_products', description_translation_key: 'app_focus_modes.business.price_products.description' },
        ],
    },
};

// contract-test: tooling
test('resolvesToText requires a string .text leaf and optionally non-empty text', () => {
    const en = { a: { ...t('A'), b: t('') }, c: {} };
    assert.equal(resolvesToText(en, 'a'), true);
    assert.equal(resolvesToText(en, 'a.b'), true);
    assert.equal(resolvesToText(en, 'a.b', { nonEmpty: true }), false);
    assert.equal(resolvesToText(en, 'c'), false);
    assert.equal(resolvesToText(en, 'missing.key'), false);
});

// contract-test: tooling
test('collects every *_translation_key nested in app metadata', () => {
    const keys = collectMetadataKeyRefs(metadata).map(ref => ref.key);
    assert.ok(keys.includes('app_focus_modes.business.price_products.description'));
    assert.ok(keys.includes('app_skills.business.company_financials'));
    assert.equal(keys.length, 6);
});

// Failing fixture: the dev regression where price_products had no app_focus_modes entry at all.
// contract-test: tooling
test('fails when a focus mode name key is missing from en.json', () => {
    const errors = validateAppTranslationKeys({ locales: locales({ priceProductsEn: false }), languageCodes: LANGS, appsMetadata: metadata });
    assert.ok(errors.some(e => e.includes("'app_focus_modes.business.price_products'") && e.includes('[T:')), errors.join('\n'));
    assert.ok(errors.some(e => e.includes("'app_focus_modes.business.price_products.description'")));
});

// contract-test: tooling
test('fails when a focus mode name/description exists only in English', () => {
    const errors = validateAppTranslationKeys({ locales: locales(), languageCodes: LANGS, appsMetadata: metadata });
    assert.deepEqual(errors, [
        "focus mode business.price_products: 'app_focus_modes.business.price_products' has no translation for de, fr",
        "focus mode business.price_products: 'app_focus_modes.business.price_products.description' has no translation for de, fr",
    ]);
});

// contract-test: tooling
test('passes when every focus mode is translated in every locale', () => {
    const all = locales();
    for (const lang of ['de', 'fr']) all[lang].app_focus_modes.business.price_products = { ...t(`P ${lang}`), description: t(`D ${lang}`) };
    assert.deepEqual(validateAppTranslationKeys({ locales: all, languageCodes: LANGS, appsMetadata: metadata }), []);
});

// contract-test: tooling
test('declared focus instruction keys and static label keys must resolve in English', () => {
    const errors = validateAppTranslationKeys({
        locales: locales(),
        languageCodes: ['en'],
        appsMetadata: {},
        declaredFocusKeys: [{ key: 'focus_modes.business_price_products.process', where: 'app.yml' }],
        staticRefs: [{ key: 'app_skills.business.company_financials', where: 'ok.svelte:1' }, { key: 'settings.nope.label', where: 'bad.svelte:2' }],
    });
    assert.equal(errors.length, 2);
    assert.match(errors[0], /focus instructions: 'focus_modes\.business_price_products\.process'/);
    assert.match(errors[1], /static key: 'settings\.nope\.label' \(bad\.svelte:2\)/);
});

// contract-test: tooling
test('static scan picks labelKey/*_translation_key literals and skips tests, previews and dotless values', () => {
    const files = {
        'src/components/A.svelte': "const items = [{ labelKey: 'settings.a.b' }, { labelKey: 'price' }];\nname_translation_key: \"apps.x\"",
        'src/components/A.preview.ts': "labelKey: 'never.checked'",
        'src/components/__tests__/x.ts': "labelKey: 'never.checked'",
    };
    const refs = scanStaticKeyRefs(Object.keys(files), file => files[file]);
    assert.deepEqual(refs.map(ref => ref.key), ['settings.a.b', 'apps.x']);
});

// contract-test: tooling
test('reads raw app.yml focus process/systemprompt keys and ignores disabled focus modes', () => {
    const root = mkdtempSync(join(tmpdir(), 'app-keys-'));
    mkdirSync(join(root, 'business'));
    writeFileSync(join(root, 'business', 'app.yml'), [
        'focuses:',
        '  - id: price_products',
        '    process_translation_key: focus_modes.business_price_products.process',
        '  - id: hidden',
        '    default_enabled: false',
        '    systemprompt_translation_key: focus_modes.business_hidden.systemprompt',
    ].join('\n'));
    assert.deepEqual(collectDeclaredFocusInstructionKeys(root).map(ref => ref.key), ['focus_modes.business_price_products.process']);
});
