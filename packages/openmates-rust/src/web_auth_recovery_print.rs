//! Recovery-key print page for the web client, owned by the shared core so the
//! document is identical on every platform. Mirrors `generatePrintPageHtml` in
//! `utils/recoveryKeyUtils.ts` byte for byte (including its lack of HTML
//! escaping: callers pass the generated recovery key and i18n strings only).
//! Download, clipboard and `window.open` stay in the page adapter.
//! spec: specifications/features/auth#auth.recovery.email-delay
use serde::Deserialize;

/// Translated strings of the print page (`PrintTranslations`).
#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct PrintTranslations {
    pub title: String,
    pub warning: String,
    pub storage_title: String,
    #[serde(rename = "storage1")]
    pub storage_1: String,
    #[serde(rename = "storage2")]
    pub storage_2: String,
    #[serde(rename = "storage3")]
    pub storage_3: String,
    #[serde(rename = "storage4")]
    pub storage_4: String,
}

/// HTML document for printing `recovery_key`.
pub(crate) fn print_page_html(recovery_key: &str, t: &PrintTranslations) -> String {
    let mut out = String::new();
    out.push_str("\n        <!DOCTYPE html>\n        <html>\n        <head>\n            <title>");
    out.push_str(&t.title);
    out.push_str("</title>\n            <style>\n                body {\n                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;\n                    padding: 40px;\n                    max-width: 600px;\n                    margin: 0 auto;\n                }\n                h1 {\n                    color: #333;\n                    font-size: 24px;\n                    margin-bottom: 20px;\n                }\n                .warning {\n                    background: #fff3cd;\n                    border: 1px solid #ffc107;\n                    border-radius: 8px;\n                    padding: 16px;\n                    margin-bottom: 24px;\n                }\n                .warning p {\n                    margin: 0;\n                    color: #856404;\n                }\n                .key-container {\n                    background: #f5f5f5;\n                    border: 2px dashed #ccc;\n                    border-radius: 8px;\n                    padding: 20px;\n                    text-align: center;\n                }\n                .recovery-key {\n                    font-family: 'Courier New', monospace;\n                    font-size: 18px;\n                    font-weight: bold;\n                    letter-spacing: 2px;\n                    word-break: break-all;\n                    color: #333;\n                }\n                .instructions {\n                    margin-top: 24px;\n                    color: #666;\n                    font-size: 14px;\n                }\n                .instructions li {\n                    margin-bottom: 8px;\n                }\n            </style>\n        </head>\n        <body>\n            <h1>🔐 ");
    out.push_str(&t.title);
    out.push_str("</h1>\n            <div class=\"warning\">\n                <p><strong>⚠️ ");
    out.push_str(&t.warning);
    out.push_str("</strong></p>\n            </div>\n            <div class=\"key-container\">\n                <div class=\"recovery-key\">");
    out.push_str(recovery_key);
    out.push_str("</div>\n            </div>\n            <div class=\"instructions\">\n                <p><strong>");
    out.push_str(&t.storage_title);
    out.push_str("</strong></p>\n                <ul>\n                    <li>");
    out.push_str(&t.storage_1);
    out.push_str("</li>\n                    <li>");
    out.push_str(&t.storage_2);
    out.push_str("</li>\n                    <li>");
    out.push_str(&t.storage_3);
    out.push_str("</li>\n                    <li>");
    out.push_str(&t.storage_4);
    out.push_str("</li>\n                </ul>\n            </div>\n        </body>\n        </html>\n    ");
    out
}
