/** Hide assistant speech directions in the read projection, preserving source.
 * Keep the cue allowlist synchronized with assistant_speech/projection.py.
 * Code examples and user/write-mode content remain literal.
 */
const CUES = "curious|excited|thoughtful|whispers|laughs|short pause";
const CUE_OR_CODE = new RegExp(
  "(?<ticks>`+)[\\s\\S]*?(?:\\k<ticks>|$)|(?<tildes>~{3,})[\\s\\S]*?(?:\\k<tildes>|$)" +
    `|<!--\\s*voice:(?:${CUES})\\s*-->` +
    "|<!--\\s*voice:[^>]*$",
  "g",
);

export function stripVoiceDeliveryCues(markdown: string): string {
  return markdown.replace(CUE_OR_CODE, (match) =>
    match.startsWith("<!--") ? " " : match,
  );
}
