/**
 * Sample decks for the slides component previews, unit tests and the E2E
 * fixture. `hostileDeck` carries every attack of the security contract; it must
 * render inert (assertion slides.security.host-rendered-and-isolated).
 */

export function sampleDeck(aspect: '16:9' | '16:10' | '4:3' = '16:9'): string {
  return `<deck title="Quarterly review" aspect="${aspect}" template="builtin:plain">
  <slide id="s1" layout="title">
    <text id="e1" role="title">Quarterly review</text>
    <text id="e2" role="subtitle">Results, risks and next steps</text>
    <notes>Welcome everyone.</notes>
  </slide>
  <slide id="s2" layout="title-and-content" transition="fade">
    <text id="e3" role="title">Highlights</text>
    <text id="e4" role="body" animate="fade"><ul><li>Revenue up <b>18%</b></li><li>Two new regions</li><li>Churn <i>down</i></li></ul></text>
    <shape id="e5" kind="rect" fill="accent" x="120" y="220" w="400" h="12"/>
    <notes>Stress the eighteen percent.</notes>
  </slide>
  <slide id="s3" layout="two-column">
    <text id="e6" role="title">Plan</text>
    <text id="e7" role="body">Build</text>
    <text id="e8" role="body" step="1" animate="appear">Launch</text>
    <video id="e9" src="youtube:abc123xyz" x="1000" y="600" w="600" h="338"/>
    <notes>Mention the discount only if asked.</notes>
  </slide>
  <slide id="s4" layout="quote">
    <text id="e10" role="quote">Make it work, then make it right.</text>
    <text id="e11" role="caption">The team</text>
    <todo id="e12" title="Next" x="120" y="760" w="800" h="240"><item done="true">Ship</item><item done="false">Review</item></todo>
  </slide>
</deck>
`;
}

export const hostileDeck = `<deck title="Hostile">
  <slide onclick="window.__slidesPwned = true">
    <text role="title" onclick="window.__slidesPwned = true" style="position:fixed" data-x="1">Safe title<script>window.__slidesPwned = true</script></text>
    <image src="https://evil.example/pixel.png" x="1" y="1" w="1" h="1"/>
    <image src="data:image/png;base64,AAAA"/>
    <iframe src="https://evil.example"></iframe>
    <object data="x"></object>
    <marquee>unknown</marquee>
    <link href="javascript:window.__slidesPwned = true">bad</link>
    <text role="body"><a href="javascript:alert(1)">no anchors</a><img src="x" onerror="window.__slidesPwned = true"></text>
  </slide>
</deck>`;
