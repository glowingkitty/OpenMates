/**
 * App-store examples for the news skill.
 *
 * Captured from real Brave news responses with everyday lifestyle queries (travel, food, culture).
 */

export interface NewsSearchStoreExample {
  id: string;
  query: string;
  query_translation_key?: string;
  provider?: string;
  status: 'finished';
  results: Array<Record<string, unknown>>;
  url?: string;
}

const examples: NewsSearchStoreExample[] = [
  {
    "id": "store-example-news-search-1",
    "query": "European travel trends for summer 2026",
    "query_translation_key": "settings.app_store_examples.news.search.1",
    "provider": "Brave Search",
    "status": "finished",
    "results": [
      {
        "title": "Despite Safety Concerns, Travelers Still Want to Explore New Destinations in 2026",
        "url": "https://travelandleisure.com/travel-safety-concerns-in-2026-11944614",
        "description": "These Destinations Are Trending for Solo Travelers in 2026, According to New Data ... The U.S. Just Issued a Global Travel Warning—What Travelers Should Know About the Worldwide Security Alert · This European Country Got Issued a Travel Advisory Amid Record Visitor Numbers in 2025—What to Know",
        "page_age": "2 days ago",
        "meta_url": {
          "favicon": "https://imgs.search.brave.com/MOAj6XcGwxkFvzUu7uOl7D8T437SgO33jWEmSo9qU20/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvYzM1NjA4NThk/MTk1OTY2NTExNjFl/NGY2ZjMwZGUzNDFm/MjZkYmEyMmY4OGM0/NDM2YjA1ODNmMWVi/OWRlOTI5Ni90cmF2/ZWxhbmRsZWlzdXJl/LmNvbS8"
        },
        "thumbnail": {
          "src": "https://imgs.search.brave.com/uFl8imYfLeGf2mULWwOwb93n6m5Mtx391Iixbj0M58o/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly93d3cu/dHJhdmVsYW5kbGVp/c3VyZS5jb20vdGht/Yi9ZYzBqMU9sS3Mz/Z1pnc0JfaXpqSFEz/N2hWck09LzE1MDB4/MC9maWx0ZXJzOm5v/X3Vwc2NhbGUoKTpt/YXhfYnl0ZXMoMTUw/MDAwKTpzdHJpcF9p/Y2MoKS9UQUwtYW54/aW91cy10cmF2ZWxl/ci1UUkFWRUxDT05D/RVJOUzA0MjYtOTBi/ZTk3MDkzNWNmNDE3/N2E0Mjk3NzI1ZWJh/MjE1ZWQuanBn"
        },
        "extra_snippets": [
          "Sickness and injury abroad is a major concern to 31 percent of travelers surveyed, followed by unrest and terrorism.",
          "These Are the Biggest Travel Trends of 2025, According to Expedia ... The U.S. Has 22 Countries On Its 'Do Not Travel' List for 2026—What Travelers Should Know",
          "“Travelers are clearly prioritizing discovery in 2026,” Richards said. “Whether it’s a first-time destination or an entirely new region, that sense of exploration comes with added complexity, and it reinforces why medical, security and evacuation preparedness remain essential.” ... All comments are subject to our Community Guidelines. Travel + Leisure does not endorse the opinions and views shared by readers in our comment sections. ... These Are the Biggest Travel Trends for 2026, According to 14 Industry Leaders—and the Destinations Everyone's Talking About",
          "How to Maximize PTO Like Gen Z—and More 2026 Travel Trends"
        ]
      },
      {
        "title": "Germany Joins Spain, France, Italy, and Portugal in Implementing Significant Increases in Tourist Taxes to Combat Overcrowding, Enhance Local Infrastructure, and Ensure Sustainable Growth of Europe’s Tourism Industry in 2026 - Travel And Tour World",
        "url": "https://www.travelandtourworld.com/news/article/germany-joins-spain-france-italy-and-portugal-in-implementing-significant-increases-in-tourist-taxes-to-combat-overcrowding-enhance-local-infrastructure-and-ensure-sustainable-growth-of-europes/",
        "description": "Canadians heading to Europe in 2026 should take note of the growing trend of tourist taxes being introduced across key destinations. Aimed at tackling the challenges of overcrowding and strained infrastructure, these charges apply to overnight visitors and are becoming an increasingly common way for European cities to regulate the influx of tourists and sustain the local environment. In countries like Italy, one of Europe’s top tourist hotspots during the summer...",
        "page_age": "13 hours ago",
        "meta_url": {
          "favicon": "https://imgs.search.brave.com/7SOirWtnu6586L9NdaQITqJ2GQ_2W3ATMUy9R1P9n-8/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvYWZmYTkxNTgz/Njg1OGU0NjQ4Y2Nj/NDliMjYxYzE4MzJk/Y2I1MjE5NWFlYjI2/MDNiNTQyZGE0MTE3/OTM5MmMwYi93d3cu/dHJhdmVsYW5kdG91/cndvcmxkLmNvbS8"
        },
        "thumbnail": {
          "src": "https://imgs.search.brave.com/5rEjwIZMikJMwcMKV4sTkoSoc_yN0-6b13D1nds6ODw/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly93d3cu/dHJhdmVsYW5kdG91/cndvcmxkLmNvbS93/cC1jb250ZW50L3Vw/bG9hZHMvMjAyNi8w/NC9pc3RvY2twaG90/by0xMTYxOTA2NDMz/LTYxMng2MTItMS5q/cGc"
        },
        "extra_snippets": [
          "Canadians heading to Europe in 2026 should take note of the growing trend of tourist taxes being introduced across key destinations. Aimed at tackling the challenges of overcrowding and strained infrastructure, these charges apply to overnight visitors and are becoming an increasingly common way for European cities to regulate the influx of tourists and sustain the local environment. In countries like Italy, one of Europe’s top tourist hotspots during the summer, a “city tax” is now applied to visitors in numerous cities.",
          "Germany joins Spain, France, Italy, and Portugal in introducing new tourist taxes in 2026 to tackle overcrowding, enhance infrastructure, and secure future tourism.",
          "Canadians heading to Europe in 2026 will need to budget for increasing city taxes, attraction fees, and the upcoming ETIAS travel authorization. These new fees are being introduced to help manage the growing number of visitors and ensure that European cities can continue to provide high-quality tourism experiences.",
          "Home » EUROPE » Germany Joins Spain, France, Italy, and Portugal in Implementing Significant Increases in Tourist Taxes to Combat Overcrowding, Enhance Local Infrastructure, and Ensure Sustainable Growth of Europe’s Tourism Industry in 2026 ... As European destinations continue to grapple with the growing influx of tourists, Germany has joined Spain, France, Italy, and Portugal in implementing new higher tourist taxes."
        ]
      },
      {
        "title": "Europe Revamps Travel Rules for 2026 with New Tourist Taxes, Visitor Limits, Border Checks and Sustainable Tourism Policies: All You Need to Know - Travel And Tour World",
        "url": "https://travelandtourworld.com/news/article/europe-revamps-travel-rules-for-2026-with-new-tourist-taxes-visitor-limits-border-checks-and-sustainable-tourism-policies-all-you-need-to-know",
        "description": "Discover Europe’s updated travel regulations for 2026 including tourist taxes, entry systems, visitor caps and border control changes reshaping holidays.",
        "page_age": "1 day ago",
        "meta_url": {
          "favicon": "https://imgs.search.brave.com/1MwaBu2-bzwGWxa1IswWGIH09IkSJS3JEoBQWAX5MbM/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvNjdmZjZiOGVi/OWU0NmRhZDg4YjU1/ODEzMTNhNjI1N2Fk/NDg1MjAxMTE3Yjg5/MGY4MmZmYTUwOTg1/MTcxMjJiZS90cmF2/ZWxhbmR0b3Vyd29y/bGQuY29tLw"
        },
        "thumbnail": {
          "src": "https://imgs.search.brave.com/-KxGiYiW4nJr9-mFoloolA6zdGTSAeBwy73JVLBcRSs/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly93d3cu/dHJhdmVsYW5kdG91/cndvcmxkLmNvbS93/cC1jb250ZW50L3Vw/bG9hZHMvMjAyNi8w/NC9hLXBob3RvZ3Jh/cGgtb2YtYS1idXN0/bGluZy1ldXJvcGVh/bi1jaXR5X1Y2VTl0/UkpmUmlLRVBPV1N0/Q2hSSndfWXBnYl9k/alNTek8zYTloWFpH/QlFyQV9jb3Zlcl9z/ZC5qcGVn"
        },
        "extra_snippets": [
          "These measures are rooted in official strategies to balance the social, environmental and economic impacts of tourism while ensuring positive experiences for both travellers and local communities. Europe’s border controls are entering a new era in 2026 with the full rollout of the European Union Entry/Exit System (EES).",
          "Travellers should also monitor official tourism and government websites for the latest updates, as new systems like ETIAS are expected to launch later in 2026 — affecting entry procedures for many non‑EU visitors. These policy changes are rooted in wider European tourism strategy, which seeks to preserve Europe’s status as a leading global destination while also protecting landscapes, cultural heritage and resident wellbeing.",
          "Travellers should plan ahead and secure entry reservations to avoid disappointment, especially in summer months when demand surges. The United Kingdom, though no longer part of the EU, has also updated its tourism entry requirements. Visitors from visa‑exempt countries, including the United States, must now obtain an Electronic Travel Authorisation (ETA) before arrival. The UK ETA system functions similarly to the soon‑to‑launch EU ETIAS (European Travel Information and Authorisation System) and represents both a security measure and a form of official fee for entry.",
          "This trend reflects a broader governmental focus on balancing tourism’s economic benefits with social and quality‑of‑life concerns for permanent residents, especially in high‑traffic hubs where short‑stay rentals have historically surged. Planning a trip to Europe in 2026 requires staying informed about evolving rules:"
        ]
      },
      {
        "title": "New Europe Travel Era Begins with Fully Operational Entry Exit System Changing How Tourists Enter and Exit the Schengen Zone - Travel And Tour World",
        "url": "https://travelandtourworld.com/news/article/new-europe-travel-era-begins-with-fully-operational-entry-exit-system-changing-how-tourists-enter-and-exit-the-schengen-zone",
        "description": "Europe launches Entry Exit System across 29 countries from April 10, 2026, replacing passport stamps with biometric travel tracking.",
        "page_age": "17 hours ago",
        "meta_url": {
          "favicon": "https://imgs.search.brave.com/1MwaBu2-bzwGWxa1IswWGIH09IkSJS3JEoBQWAX5MbM/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvNjdmZjZiOGVi/OWU0NmRhZDg4YjU1/ODEzMTNhNjI1N2Fk/NDg1MjAxMTE3Yjg5/MGY4MmZmYTUwOTg1/MTcxMjJiZS90cmF2/ZWxhbmR0b3Vyd29y/bGQuY29tLw"
        },
        "thumbnail": {
          "src": "https://imgs.search.brave.com/uu62wqfXjtUUAdgV_4RAGfMeQmmPcg-EvHFm9dHp1Ww/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly93d3cu/dHJhdmVsYW5kdG91/cndvcmxkLmNvbS93/cC1jb250ZW50L3Vw/bG9hZHMvMjAyNi8w/NC9hLXBob3RvZ3Jh/cGgtb2YtYS1idXNp/bmVzcy10cmF2ZWxl/ci1zaXR0Xy1JWjdv/Tko1UjMyVzQwcmxS/dHU0Mndfd05IcExn/OUdRbUtRNW9vcS1Y/VUs5Z19jb3Zlci0x/LmpwZw"
        },
        "extra_snippets": [
          "Home » European Travel News » New Europe Travel Era Begins with Fully Operational Entry Exit System Changing How Tourists Enter and Exit the Schengen Zone ... Europe has stepped into a bold new travel chapter. From April 10, 2026, the Entry Exit System is fully active across 29 countries.",
          "Official European Union travel platforms have confirmed that the Entry Exit System is fully implemented from April 10, 2026. National government portals, including those from key Schengen states, have aligned with this timeline. Parliamentary research bodies in Europe have also validated the same rollout date.",
          "The excitement of exploring cities like Paris, Rome, or Amsterdam now begins with a modern border experience. It may feel different at first. But it reflects a continent preparing for the future. Travel is evolving. Europe is leading that change. And from April 10, 2026, every step across its borders tells that story.",
          "The move is confirmed by official European Union platforms and government portals. It marks one of the biggest changes in modern travel history. Every non-EU visitor now enters a system built on biometric identity and automated control. The familiar passport stamp is now history across the Schengen zone. Authorities have removed manual stamping and replaced it with a digital record. Travellers entering Europe must now provide fingerprints and a facial scan."
        ]
      }
    ]
  },
  {
    "id": "store-example-news-search-2",
    "query": "Healthy eating recommendations in Europe",
    "query_translation_key": "settings.app_store_examples.news.search.2",
    "provider": "Brave Search",
    "status": "finished",
    "results": [
      {
        "title": "Confused About the New Cholesterol Guidelines? Here’s What to Know. - The New York Times",
        "url": "https://www.nytimes.com/2026/04/09/well/cholesterol-guidelines-heart-disease.html",
        "description": "New recommendations suggest that some people should start trying to lower their cholesterol as early as age 30.",
        "page_age": "2 days ago",
        "meta_url": {
          "favicon": "https://imgs.search.brave.com/lWA-zkTMlWM2cUvrcYa1Fls86e-Vl-rkSBOjichQqVs/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvMGFlZWRkYmVh/YWFhZmFjYjM4MWYy/NTQzZmExMTIwN2Nm/NGJmZjgwYTRhYjI5/OTliM2JkYmI2MWY0/M2RlOGFlMi93d3cu/bnl0aW1lcy5jb20v"
        },
        "thumbnail": {
          "src": "https://imgs.search.brave.com/hLpQ5YFW6cwaDelO9_7z8rn-Y89fGQvoYb3g9rsWCmI/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly9zdGF0/aWMwMS5ueXQuY29t/L2ltYWdlcy8yMDI2/LzA0LzA5L3dlbGwv/MDlXRUxMLUNIT0xF/U1RFUk9MLUNPTkZV/U0lPTi1pbWFnZS8w/OVdFTEwtQ0hPTEVT/VEVST0wtQ09ORlVT/SU9OLWltYWdlLWZh/Y2Vib29rSnVtYm8u/anBn"
        },
        "extra_snippets": [
          "It’s never too early to talk with your doctor about your risk of heart disease, and you should build heart-healthy habits like eating a Mediterranean-style or DASH diet and exercising regularly as soon as possible. But starting at age 30, the conversation can include an actual prediction of your future risk.",
          "Nina Agrawal is a Times health reporter.",
          "The guidelines also recommend that all adults now have levels of Lipoprotein(a), a genetically determined form of cholesterol, tested at least once. Lp(a) increases the risk of heart disease, regardless of your other lipid levels. “It’s an amplifier of whatever your risk is,” said Dr.",
          "Measuring long-term risk is particularly useful for people 30 to 59. Doctors might look at a younger patient who isn’t at risk of heart disease in the next 10 years, but could be in the long-term, and recommend that they start taking a statin."
        ]
      },
      {
        "title": "Roundup: Updated Dietary Guidelines Stress Less Meat, More Plant-Based Proteins; and More News",
        "url": "https://baptisthealth.net/baptist-health-news/dietary-guidelines-stress-less-meat-and-more-plant-based-proteins",
        "description": "Regarding fats, the AHA now broadly recommends choosing foods rich in unsaturated fats over those high in saturated fats, rather than just focusing on cooking oils. ... Low-fat and fat-free dairy remain the preferred choices to help control overall calorie and fat intake. Meanwhile, the AHA takes a firmer stance against ultra-processed foods. Research consistently links highly processed items to poor health outcomes, so the new guidance emphasizes eating ...",
        "page_age": "2 days ago",
        "meta_url": {
          "favicon": "https://imgs.search.brave.com/X4BjzGHik1IapBYtSQjqXt0ABqKJ2preubjCxqDXKHo/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvZWU4MGMyMzY4/YmY4MDVkMTg2YjUy/Mzc1YjkxOGM4ZWVi/YzIzMmNlZjVkOGUz/N2M5ZmM0OGM3ZjA3/MTlmYzQ5NS9iYXB0/aXN0aGVhbHRoLm5l/dC8"
        },
        "thumbnail": {
          "src": "https://imgs.search.brave.com/NOMKwUhEyAqIKveKPjar___Ou4tuATncs5WOtrfOFk8/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly9iYXB0/aXN0aGVhbHRoLm5l/dC9jb250ZW50L2Fz/c2V0cy9pbWFnZXMv/b3Blbi1ncmFwaC9s/b2dvLnBuZw"
        },
        "extra_snippets": [
          "Regarding fats, the AHA now broadly recommends choosing foods rich in unsaturated fats over those high in saturated fats, rather than just focusing on cooking oils. ... Low-fat and fat-free dairy remain the preferred choices to help control overall calorie and fat intake. Meanwhile, the AHA takes a firmer stance against ultra-processed foods. Research consistently links highly processed items to poor health outcomes, so the new guidance emphasizes eating minimally processed foods to avoid hidden additives.",
          "Focus on your overall eating pattern rather than stressing over single ingredients. Every time you swap an unhealthy food for a nutritious alternative, you take a measurable step toward reducing your risk of heart disease and improving your quality of life. A recent large study published in JAMA Network Open highlights an important public health issue: not all women in the U.S. are getting recommended mammograms at the same rate.",
          "The 2026 update to the American Heart Association’s dietary guidelines, the first one since 2021, is focused on making important swaps — such as replacing red meat with plant-based proteins — that can make a lasting impact.",
          "While progress has been made, where a woman lives and access to resources still play a major role in receiving recommended breast cancer screenings. Closing these gaps is essential to improving outcomes and ensuring that all women benefit from early detection. For years, health experts have reinforced the strategy that staying active is vital for staying healthy. A new major study published in the European Heart Journal suggests that how hard you move might be even more important than how long you move."
        ]
      },
      {
        "title": "What ‘eating healthy’ really means and how to start improving your diet - BCTV",
        "url": "https://bctv.org/2026/04/09/what-eating-healthy-really-means-and-how-to-start-improving-your-diet",
        "description": "From Capital Blue Cross From the moment food first flew toward us on a spoon with airplane noises, we’ve been eating. Our bodies need the nourishment to survive and as […]",
        "page_age": "3 days ago",
        "meta_url": {
          "favicon": "https://imgs.search.brave.com/3R0h8F2fiR_MkpRJRGnln4eCfslCxpEmibi6Slcilaw/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvMzRiNWJiNWMw/Y2RhZDdjY2RjNTMw/NzVjYjk0ZGMxNGQ4/MTY5MDg5ZTQ0MTM1/MmM0NjA1NWVkYTY3/NDI4Y2M5ZS9iY3R2/Lm9yZy8"
        },
        "thumbnail": {
          "src": "https://imgs.search.brave.com/nj21BfU5Oo9uYtcbvnxP6wps3rX16HsmzAW0ETlwbAM/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly93d3cu/YmN0di5vcmcvd3At/Y29udGVudC91cGxv/YWRzLzIwMjYvMDQv/ZnJ1aXQucG5n"
        },
        "extra_snippets": [
          "Fill your plate with plants by eating vegetables and fruits throughout the day. Choose quality carbohydrates and fats by focusing on whole grains and incorporating healthy fats. Limit what works against your health, including highly processed foods, added sugars, refined carbohydrates, and alcoholic beverages. Putting these recommendations into practice often starts with choosing foods in their simplest, least processed forms.",
          "Let’s start with the basics. According to the 2025-2030 Dietary Guidelines for Americans, a healthy eating plan includes these recommendations:",
          "Dietitians and researchers generally define highly processed (or ultra‑processed) foods as packaged, ready‑to‑eat products that tend to be high in added sugars, sodium, and saturated fats. That said, nutritious options can be found throughout the grocery store – if you know where to look. “Reading ingredient lists and nutrition labels when grocery shopping can guide healthier choices,” Miele said.",
          "Instead, think about all the new things you’re trying and strive to eat as many colors as possible (natural colors; not processed). Get fresh, frozen, or canned fruits. A fruit is a fruit is a fruit. If it’s not something you typically have in your diet, starting anywhere is great. Don’t put pressure on yourself. You can find more exotic fruits when they’re frozen too! Try out some kiwi and mangoes. If you get fruits in a can, the healthier ones are packed in water or their own juice."
        ]
      },
      {
        "title": "New US Dietary Guidelines Unaffordable for Many Americans: Survey - Business Insider",
        "url": "https://www.businessinsider.com/new-us-dietary-guidelines-unaffordable-for-many-americans-survey-2026-4",
        "description": "The US's new serving recommendations would increase grocery bills by 32% per person, mostly due to the emphasis on meat, a Numerator survey found.",
        "page_age": "4 days ago",
        "meta_url": {
          "favicon": "https://imgs.search.brave.com/Z6wRqiE6vvL-8sy5MskRt7Tuy1z-PxXnfSbVXVy86vw/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvZTI3NGQzMDdi/ZjEzYTA0MTI4NWMw/MWVjOTFmNDI3Yzdk/NGQzZDE1OTAxOWVj/NWIxMjk3YTcyNTg5/N2FiZjM2Yy93d3cu/YnVzaW5lc3NpbnNp/ZGVyLmNvbS8"
        },
        "thumbnail": {
          "src": "https://imgs.search.brave.com/4Zsd6ER6ifEIHS6f7B3DDzpxQdLP5L8p07IAFIdp7GA/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly9pLmlu/c2lkZXIuY29tLzY5/ZDU2ODVmMWE1MTJk/MGE2M2U3MzRmMD93/aWR0aD0xMjAwJmZv/cm1hdD1qcGVn"
        },
        "extra_snippets": [
          "US secretary of Health and Human Services Robert F. Kennedy Jr. wants Americans to eat a lot more meat.",
          "New data suggests the dietary recommendations championed by US Health Secretary Robert F.",
          "The new guidelines also recommend plant-based protein sources, but Kennedy's Make America Healthy Again movement has a well-documented preference for red meat.",
          "Setting aside the government's position, Numerator's data does show that Americans are taking dietary health more seriously, increasing their shopping trips to the \"perimeter\" sections of the store that include fresh produce and dairy at a higher rate than trips to the center aisles with more heavily processed packaged foods."
        ]
      }
    ]
  },
  {
    "id": "store-example-news-search-3",
    "query": "Cultural festivals in Europe this summer",
    "query_translation_key": "settings.app_store_examples.news.search.3",
    "provider": "Brave Search",
    "status": "finished",
    "results": [
      {
        "title": "Unmissable Theatre Festivals and Performing Arts Festivals: Global Must-Sees for 2026",
        "url": "https://classicalite.com/articles/1725294/20260409/unmissable-theatre-festivals-performing-arts-festivals-global-must-sees-2026.htm",
        "description": "Many incorporate local culture too, weaving in regional dialects, folklore, or social issues. This keeps theatre festivals feeling alive and relevant, not stuck in dusty scripts. Beyond the shows, they foster communities: workshops, artist talks, and late-night pub debates extend the magic long after curtains fall. Europe ...",
        "page_age": "2 days ago",
        "meta_url": {
          "favicon": "https://imgs.search.brave.com/TOhI27KLT6Y8ASJPk1TT1c0bMLuzRDH_r47xAygeINU/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvY2Y2MWFlYWQy/YjNmNTVhMmU1ODdh/ODE1N2NiM2RiY2E2/OThlZTg5ZDQwZmNh/NWEzN2U0OGNiNDUz/ZjYwNDUxNy9jbGFz/c2ljYWxpdGUuY29t/Lw"
        },
        "thumbnail": {
          "src": "https://imgs.search.brave.com/MT6ng5Ii0Z0hcC28hGL1yfTiJ6Cbp-DYGtW7FoUKHi4/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly9kLmNs/YXNzaWNhbGl0ZS5j/b20vZW4vZnVsbC8x/NzI1NDQ3L3RoZWF0/cmUtZmVzdGl2YWwu/anBn"
        },
        "extra_snippets": [
          "Many incorporate local culture too, weaving in regional dialects, folklore, or social issues. This keeps theatre festivals feeling alive and relevant, not stuck in dusty scripts. Beyond the shows, they foster communities: workshops, artist talks, and late-night pub debates extend the magic long after curtains fall. Europe claims many premier theatre festivals, rooted in centuries of stagecraft.",
          "Experience the world's top theatre festivals and performing arts festivals in 2026—from Edinburgh Fringe's massive stages to Avignon's street spectacles.",
          "Athens Epidaurus Festival (Greece, summer): Ancient amphitheaters host Greek tragedies under starlit skies, echoing Sophocles and Euripides with perfect acoustics that carry whispers to the back rows.",
          "Belgium's Kunstenfestivaldesarts in Brussels mixes dance and theatre in May, drawing avant-garde crowds to industrial spaces. The Holland Festival in Amsterdam spans June with world premieres, while London's Battersea Arts Centre hosts fringe-style innovation year-round. Each adds layers to Europe's rich tapestry, proving the region dominates for depth and density of options."
        ]
      },
      {
        "title": "Six uniquely German music festivals you won't want to miss in spring 2026",
        "url": "https://thelocal.de/20260410/six-uniquely-german-music-festivals-you-wont-want-to-miss-in-spring-2026",
        "description": "The Africa Festival Würzburg is ... and culture in Europe. Photo: picture alliance/dpa | Nicolas Armer · Germany’s music festival season gets underway in late April and May with an eclectic mix of springtime events. Many of these are smaller, more personal gatherings that reward curiosity and a sense of adventure. Before the mega‑festivals of high summer take over ...",
        "page_age": "1 day ago",
        "meta_url": {
          "favicon": "https://imgs.search.brave.com/q6JIxhGX9YHU2gsf-G7a1rCQQuxl6_ulcgACqDyOFuc/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvMWYxMmMwMTNh/MWNiYmExNDJjNTU2/ZDUwZDQyZTkwOTY3/M2NhNTI2N2Y4YmY1/MzZlZjExZmJkOGRi/Zjc2NWM3MC90aGVs/b2NhbC5kZS8"
        },
        "thumbnail": {
          "src": "https://imgs.search.brave.com/floA3Huus8XaPI98RJEkpWemSSK1sdTojSLIU6sR97o/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly9hc3Nl/dHMudGhlbG9jYWwu/Y29tL2Nkbi1jZ2kv/cnM6Zml0OjEyMDAv/cXVhbGl0eTo3NS9w/bGFpbi9odHRwczov/L2FwaXdwLnRoZWxv/Y2FsLmNvbS93cC1j/b250ZW50L3VwbG9h/ZHMvMjAyNi8wNC93/YXRlcm1hcmtzLWxv/Z28tNTM3ODU4Njg2/LmpwZ0B3ZWJw"
        },
        "extra_snippets": [
          "The Africa Festival Würzburg is one of the largest festivals for African music and culture in Europe. Photo: picture alliance/dpa ",
          " Nicolas Armer · Germany’s music festival season gets underway in late April and May with an eclectic mix of springtime events. Many of these are smaller, more personal gatherings that reward curiosity and a sense of adventure. Before the mega‑festivals of high summer take over fields and raceways, Germany quietly eases itself into the season with a run of spring festivals that can feel more intimate and – for many – more rewarding.",
          "The festival mainly attracts people who love festival culture itself – camping, costumes and social energy – more than any particular genre. Tickets usually cost around €70, with camping included and generally regarded as essential to the experience. READ ALSO: Nine hip-hop tracks that will help you learn German ... The Immergut (always good) Festival offers one of the calmest and most reflective starts to the festival summer.",
          "The Africa Festival Würzburg is one of Europe’s longest‑running celebrations of African music and culture.",
          "The audience is culturally curious and multi‑generational. Day passes usually start at around €60, with multi‑day tickets also available. May 22nd – 25th: Sputnik Spring Break, Bitterfeld · While the other festivals on this list tend to be smaller and more intimate, Sputnik Spring Break is where Germany’s spring festival season turns up the volume."
        ]
      },
      {
        "title": "2026 festivals: Reading and Leeds, Big Weekend, Download and the other big festivals taking place this summer",
        "url": "https://bbc.com/news/articles/cn430vqwznyo",
        "description": "Glastonbury is having a fallow year but there are huge line-ups at many other festivals this year - and something different if you fancy that too.",
        "page_age": "1 day ago",
        "meta_url": {
          "favicon": "https://imgs.search.brave.com/kfRy7wuGNQWzU47LzCO0VZPfeuEgMwKe1nZIYNJS9SU/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvODczZDE3NmVj/MzFhZjM1Yzc3YjA0/YTdhM2NkYTkxMGM5/NmQ5Yjc4YTBmMjY2/MTMzNWE1MzgwOWNm/NGQ3YWZlYy9iYmMu/Y29tLw"
        },
        "thumbnail": {
          "src": "https://imgs.search.brave.com/8vaG3npyX9YFoMDLcPHMnysfkwgX7-E95vpWBnfNhYc/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly9pY2hl/Zi5iYmNpLmNvLnVr/L25ld3MvMTAyNC9i/cmFuZGVkX25ld3Mv/Yzg2ZS9saXZlLzNi/ZjUxOTQwLTM0Y2It/MTFmMS1iMWJjLTY1/NTJlMDA4ZWE0OC5q/cGc"
        },
        "extra_snippets": [
          "There are bumper line-ups for the likes of Reading and Leeds, Parklife and the Isle of Wight Festival to look forward to - and a chance for new festivals to flourish. One big event returns this year after a seven-year hiatus, and you can probably find a match for whatever genre you like. ... First let's have a look at what's around this summer if you want to make a weekend of it; sleeping bag and tent at the ready.",
          "Dance music events are a staple of the UK summer festival calendar - this year's Creamfields has an impressive set of names coming to Cheshire, including Swedish House Mafia, Martin Garrix and Armin van Buuren from 27 to 30 August.",
          "After warm sunshine beamed down on large parts of the UK this week, it's easy to picture the summer festival season that awaits.",
          "Meanwhile a new festival series is coming to Leeds this summer - Roundhay has announced its first shows for July with headline performances from Pitbull and Lewis Capaldi."
        ]
      },
      {
        "title": "American Tourists Warned Of $1,800 Fines For Dress Code Ban In The Most Popular Vacation Destinations In Europe",
        "url": "https://www.thetravel.com/american-tourists-warned-of-fines-for-dress-code-in-vacation-destinations-in-europe/",
        "description": "Americans heading to Europe this summer should be wary of dress code bans that can carry fines of up to $1,800.",
        "page_age": "2 days ago",
        "meta_url": {
          "favicon": "https://imgs.search.brave.com/8_oXWBFN7FVq0-asWgua_jFPnPWE_W0t1nxZvkOQTZg/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvMGMzZGU2ZGQ2/M2MxZGQ1YzYxZTQ4/ZDEwMjZlOWM4MTI5/YzIyOGFmYTAxOTU4/MWRjMDJmNThiZGI3/ZDMyOTI5OS93d3cu/dGhldHJhdmVsLmNv/bS8"
        },
        "thumbnail": {
          "src": "https://imgs.search.brave.com/NsO1dWSzWfA2cfct-7ta__WDD_6gArlSVNdybXhSODY/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly9zdGF0/aWMwLnRoZXRyYXZl/bGltYWdlcy5jb20v/d29yZHByZXNzL3dw/LWNvbnRlbnQvdXBs/b2Fkcy8yMDI1LzAy/L2FsYnVmZWlyYS1w/b3J0dWdhbC1qdW5l/LTI0LTIwMjMtdG91/cmlzdHMtcmVsYXhp/bmctYXQtc2Vhc2lk/ZS1yZXNvcnQtdG93/bi1vZi1hbGJ1ZmVp/cmEtaW4tc291dGhl/cm4tYWxnYXJ2ZS1y/ZWdpb24tb2YtcG9y/dHVnYWwtZHVyaW5n/LXRoZS1zdW1tZXIu/anBnP3c9MTYwMCZh/bXA7aD05MDAmYW1w/O2ZpdD1jcm9w"
        },
        "extra_snippets": [
          "Americans heading on one of their bucket list trips in Europe this summer may want to think twice before leaving the beach in their swimsuits. Several of Europe's most popular vacation cities now enforce strict dress code rules, banning bikinis, other beach attire, or walking around shirtless in historic centers and public streets.",
          "Across southern Europe — especially in historic coastal destinations — local governments have introduced similar bans and restrictions discouraging beachwear in city centers. Not long after Albufeira announced its changes to its Code of Conduct, Malaga also updated its rules for tourists, introducing dress code restrictions with them. These rules are often framed as being about respect for cultural heritage and local residents.",
          "Always research the laws and general customs and culture of any new place ahead of your trip to avoid issues during your visit. For American travelers used to more relaxed beach-town norms in places like Florida or Southern California, these rules can come as a surprise. Tropea town and beach - Calabria, Italy, EuropeCredit: Shutterstock",
          "The warning comes after officials in Albufeira, one of Portugal's busiest resort hubs, introduced new penalties targeting tourists who walk through town in swimwear. This rule is just another example of a trend of similar dress code bans across Europe, as cities respond to overtourism and complaints from residents about how visiting tourists are behaving in their historic districts."
        ]
      }
    ]
  }
]

export default examples;
