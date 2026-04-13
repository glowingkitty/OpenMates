/**
 * App-store examples for the videos skill.
 *
 * Captured from real Brave video search. Includes one Artemis II space-mission example plus two everyday lifestyle queries.
 */

export interface VideosSearchStoreExample {
  id: string;
  query: string;
  query_translation_key?: string;
  provider?: string;
  status: 'finished';
  results: Array<Record<string, unknown>>;
  url?: string;
}

const examples: VideosSearchStoreExample[] = [
  {
    "id": "store-example-videos-search-1",
    "query": "Artemis II mission videos",
    "query_translation_key": "settings.app_store_examples.videos.search.1",
    "provider": "Brave Search",
    "status": "finished",
    "results": [
      {
        "title": "NASA’s Artemis II Crew Flies Around the Moon (Official Broadcast)",
        "url": "https://www.youtube.com/watch?v=z-j1uxBmis0",
        "description": "We're about to fly around the Moon.\n\nOn Monday, April 6, the four astronauts of Artemis II will travel farther from Earth than any humans in history—breaking the record set by Apollo 13 in 1970.\n\nThey'll sail around the far side of the Moon, photographing lunar features never before seen by human eyes. At their closest point, they'll pass roughly 4,000 miles above the lunar surface.\n\nHighlights include:\n- 1:56 p.m. EDT (1756 UTC): Artemis II crew surpasses the Apollo 13 distance record\n- 2:45 p.m. EDT (1845 UTC): Lunar observation period begins\n- 6:41 p.m. EDT (2241 UTC): Predicted loss of communications as Artemis II heads behind the moon (roughly 40 minutes)\n- 7:00 p.m. EDT (2300 UTC): Artemis II's closest approach to the Moon\n- 7:05 p.m. EDT (2305 UTC): Artemis II reaches its furthest distance from Earth\n\nLearn more about the mission timeline: https://go.nasa.gov/4c46fOu\nGet the latest images and video from the mission: https://www.nasa.gov/artemis-ii-multimedia/\n\nCredit: NASA",
        "age": "",
        "meta_url": {
          "profile_image": "https://yt3.ggpht.com/eIf5fNPcIcj9ig-wZBeq4stFy1lgjWTW1nLT5dYlFkHZprZ03QBiMcbpwNMB6XSBjrSFGtAGQg=s800-c-k-c0x00ffffff-no-rj"
        },
        "thumbnail": {
          "original": "https://i.ytimg.com/vi/z-j1uxBmis0/maxresdefault.jpg"
        },
        "viewCount": 27757898,
        "likeCount": 470280,
        "channelTitle": "NASA",
        "publishedAt": "2026-04-07T03:38:23Z",
        "duration": "PT10H10M1S"
      },
      {
        "title": "NASA’s Artemis II Crew Comes Home (Official Broadcast)",
        "url": "https://www.youtube.com/watch?v=nfhDuOHMp0A",
        "description": "Around the Moon and back. Watch the Artemis II astronauts come home.\n\nNASA's Artemis II mission is splashing down in the Pacific Ocean at about 8:07 p.m. EDT on Friday, April 10 (0007 UTC April 11). \n\nFour astronauts — three from NASA and one from the CSA (Canadian Space Agency) — make up the Artemis II crew: \n• NASA astronaut Reid Wiseman, Artemis II commander \n• NASA astronaut Victor Glover, Artemis II pilot \n• NASA astronaut Christina Koch, Artemis II mission specialist \n• Canadian Space Agency (CSA) astronaut Jeremy Hansen, Artemis II mission specialist \n\nThe Artemis II astronauts launched on April 1 for a journey of ten days that took them farther than any humans have traveled from Earth. On their Orion spacecraft, named Integrity, they flew around the Moon, making observations which will help enhance scientific understanding.  \n\nArtemis II is the first crewed flight test of NASA's Space Launch System rocket and Orion spacecraft, testing the technologies we'll need for long-term lunar exploration and human missions to Mars.\n\nRead the latest Artemis II mission updates: https://www.nasa.gov/blogs/artemis/ \nLearn more about the mission and why we're going: https://www.nasa.gov/mission/artemis-ii/\n\nCredit: NASA",
        "age": "",
        "meta_url": {
          "profile_image": "https://yt3.ggpht.com/eIf5fNPcIcj9ig-wZBeq4stFy1lgjWTW1nLT5dYlFkHZprZ03QBiMcbpwNMB6XSBjrSFGtAGQg=s800-c-k-c0x00ffffff-no-rj"
        },
        "thumbnail": {
          "original": "https://i.ytimg.com/vi/nfhDuOHMp0A/maxresdefault.jpg"
        },
        "viewCount": 21877649,
        "likeCount": 513955,
        "channelTitle": "NASA",
        "publishedAt": "2026-04-11T02:37:28Z",
        "duration": "PT3H53M41S"
      },
      {
        "title": "NASA's Artemis II Crew Launches To The Moon (Official Broadcast)",
        "url": "https://www.youtube.com/watch?v=Tf_UjBMIzNo",
        "description": "We're sending astronauts around the Moon for the first time in 50 years. Come watch with us.\n\nNASA's Artemis II mission is scheduled to lift off from Kennedy Space Center on April 1. The two-hour launch window starts at 6:24 p.m. EDT (2224 UTC).\n\nFour astronauts — three from NASA and one from the CSA (Canadian Space Agency) — make up the Artemis II crew:\n- NASA astronaut Reid Wiseman, Artemis II commander\n- NASA astronaut Victor Glover, Artemis II pilot\n- NASA astronaut Christina Koch, Artemis II mission specialist\n- Canadian Space Agency (CSA) astronaut Jeremy Hansen, Artemis II mission specialist\n\nAfter launching into space atop NASA's Space Launch System (SLS) rocket, the crew will journey around the Moon and back in their Orion spacecraft, named Integrity, on an approximately 10-day mission. Artemis II will be the first crewed flight test of SLS and Orion, testing the technologies we'll need for long-term lunar exploration and human missions to Mars.\n\n24/7 streaming coverage of Artemis II operations and mission updates will be available on our YouTube channel. We're also streaming Artemis II events on NASA+, Amazon, X, Facebook, and Twitch. See the full schedule: https://www.nasa.gov/missions/artemis/artemis-2/nasa-sets-coverage-for-artemis-ii-moon-mission/\n\nEvent highlights:\n- 35:05 - Card game tradition\n- 50:55 - Crew walkout\n- 1:32:37 - Crew ingress begins\n- 2:34:47 - Rise designer interview\n- 4:15:32 - Hatch close\n- 5:21:49 - Go for launch\n- 5:36:51 - Launch\n- 5:45:24 - Main engine cutoff, core stage separation\n\nRead the latest Artemis II mission updates: https://www.nasa.gov/blogs/artemis/\n\nLearn more about the mission and why we're going: https://www.nasa.gov/mission/artemis-ii/\n\nCredit: NASA\n\n#NASA #Artemis #Space",
        "age": "",
        "meta_url": {
          "profile_image": "https://yt3.ggpht.com/eIf5fNPcIcj9ig-wZBeq4stFy1lgjWTW1nLT5dYlFkHZprZ03QBiMcbpwNMB6XSBjrSFGtAGQg=s800-c-k-c0x00ffffff-no-rj"
        },
        "thumbnail": {
          "original": "https://i.ytimg.com/vi/Tf_UjBMIzNo/maxresdefault.jpg"
        },
        "viewCount": 18814528,
        "likeCount": 448325,
        "channelTitle": "NASA",
        "publishedAt": "2026-04-01T23:43:37Z",
        "duration": "PT6H22M52S"
      },
      {
        "title": "Artemis II Explained | 2026 Mission to the Moon",
        "url": "https://www.youtube.com/watch?v=nBdjwRmJRbU",
        "description": "Artemis II is the first manned mission to the moon in over 50 years. But it's a test flight, laying the groundwork for all the future missions to come. Artemis II will not be a moon landing, but a lunar flyby. In this video, I explain what Artemis II will do, why we're flying it, and who will be the astronauts onboard. We'll talk briefly about the Space Launch System and Orion, the spacecraft for the mission.\n\n00:00 - What is Artemis 2?\n00:37 - The Artemis 2 Rocket\n02:14 - The Artemis 2 Mission\n07:04 - The Artemis 2 Crew\n09:12 - When is Artemis 2?\n\n👕 Shop my Etsy store with Artemis II merch: https://www.etsy.com/shop/DigitalAstronautShop?ref=shop-header-name&listing_id=4357561774&from_page=listing&section_id=56673231\n\n👩🚀 Read the Artemis II astronauts' bios below:\n• Reid Wiseman, Commander: https://www.nasa.gov/humans-in-space/astronauts/g-reid-wiseman/\n• Victor Glover, Pilot: https://www.nasa.gov/humans-in-space/astronauts/victor-j-glover/\n• Christina Koch, Mission Specialist: https://www.nasa.gov/humans-in-space/astronauts/christina-koch/\n• Jeremy Hansen, Mission Specialist: https://www.asc-csa.gc.ca/eng/astronauts/canadian/active/bio-jeremy-hansen.asp\n\n🚀 Read more about Artemis II: https://www.nasa.gov/mission/artemis-ii/",
        "age": "",
        "meta_url": {
          "profile_image": "https://yt3.ggpht.com/FNuHlVWktY2KNEw1CvFs0LSN7HWEipnTN6I1I368A9PrJx3vBoDBYMFxFbrRYAOvzX15D7gbyg=s800-c-k-c0x00ffffff-no-rj"
        },
        "thumbnail": {
          "original": "https://i.ytimg.com/vi/nBdjwRmJRbU/maxresdefault.jpg"
        },
        "viewCount": 4122905,
        "likeCount": 63777,
        "channelTitle": "Digital Astronaut",
        "publishedAt": "2026-01-12T13:01:36Z",
        "duration": "PT10M7S"
      }
    ]
  },
  {
    "id": "store-example-videos-search-2",
    "query": "Easy weeknight pasta recipes",
    "query_translation_key": "settings.app_store_examples.videos.search.2",
    "provider": "Brave Search",
    "status": "finished",
    "results": [
      {
        "title": "Simple One Pot Ground Beef Pasta Recipe: Perfect for Weeknights",
        "url": "https://www.youtube.com/watch?v=afM7gVxT-Q8&vl=en",
        "description": "➡ Click \"CC\" in the lower-right menu to select your subtitle language 😋 \n\n❤ My Instagram 🤗 https://www.instagram.com/EssenRecipes \n\n👉 Don’t forget to like, subscribe, and share this video if you enjoy it — it helps more than you know!\n\n0:00 Recipe #1 Simple One Pot Ground Beef Pasta Recipe: Perfect for Weeknights\n\n➡ 🖨 PRINTABLE RECIPE with Full Guide and Ingredient Substitutions: https://essenrecipes.substack.com/p/one-pot-quick-and-easy-creamy-ground-beef-pasta\n\nOne Pot Creamy Pasta with Ground Meat – Quick, Easy, and Ready in 30 Minutes! This simple recipe is made in one pan, with just a few basic ingredients. Perfect for a busy weeknight dinner – creamy, comforting, and so delicious! Try this easy and quick recipe and let me know in the comments how you love it! Have a delicious day 💖🥰😋\n\n4:42 Recipe #2 A Simple Pasta Recipe, delicious and Quick for the Whole Family\n\nThis ground beef pasta recipe tastes delicious, but it's ready in about 30 minutes! Perfect for busy weeknights. Easy creamy ground beef pasta, will please the whole family! This recipe will work with whatever your favorite pasta shape is / what you've got on hand. It's the perfect quick family meal! This recipe is very easy! Try this delicious pasta recipe with ground beef and let me now in a comments, \"How do you like it?\".\n\nINGREDIENTS:\n220 g (8 ounces) conchiglie, or any other shell-shaped pasta\n2 tbsp olive oil\npinch of salt\n1/2 medium onion\n450 g (1 pound) extra lean ground beef\n2 cloves garlic\n450 g (2 cups) tomato sauce\n1 tbsp tomato paste\n1/2 tsp Dijon mustard\n1/4 tsp Italian seasoning\n120 ml (1/2 cup) heavy / whipping cream\nBasil (optional)\nSalt & pepper to taste\nParmigiano-Reggiano (optional)\nDijon mustard (optional but recommended for building layers of flavor)\n\nPlease Subscribe, Like and Share with friends and family, or I will eat your dessert 😋🤩 \nThank you for watching 😘 Have a delicious day 😋\n\nYours, Sophie @EssenRecipes 🥰🤗",
        "age": "",
        "meta_url": {
          "profile_image": "https://yt3.ggpht.com/vR4WuUilMvRE5IQezSLWWfhcakopIg0I0PEZQl9DMNnxCta0-rko2L0mKXB6712SqgM5sWkRv5o=s800-c-k-c0x00ffffff-no-rj"
        },
        "thumbnail": {
          "original": "https://i.ytimg.com/vi/afM7gVxT-Q8/maxresdefault.jpg"
        },
        "viewCount": 3916315,
        "likeCount": 59753,
        "channelTitle": "Essen Recipes",
        "publishedAt": "2025-06-24T20:26:01Z",
        "duration": "PT8M9S"
      },
      {
        "title": "How to Make Pasta and Peas: What Italians ACTUALLY Eat at Home",
        "url": "https://www.youtube.com/watch?v=8NFqnhWHxNY",
        "description": "How to Make Pasta and Peas: What Italians ACTUALLY Eat at Home\n\nThis is the one dish that Italians actually eat at home. You won’t find this on a restaurant menu; this is the quick weeknight dinner. It is the heart of the Mediterranean diet, using simple ingredients to feed the whole family on a budget, but not intentionally to save money. It’s enjoyable because it’s wholesome, it’s fresh, and it tastes like home.\n\nIf you’ve been looking for easy one-pot pasta recipes that are healthy and delicious, this is the video for you. Growing up it was just a simple pasta and peas recipe with a sprinkle of cheese. But today, I’m showing you how to make a creamy pasta e piselli that is much better than the original!\n\nThis dish proves you don't need expensive ingredients to make authentic Italian food. This vegetarian pasta dish is ready in under 20 minutes, making it one of the best healthy meals for busy families.\n\nIngredients:  \n1 lb Ditalini pasta\n1 lb Frozen peas\n1 Yellow onion, finely chopped\n1.5 cups Pecorino Romano, grated\n4 cups Water (plus more if needed)\nOlive oil\nSalt & Pepper\n\nDirections: \n1. In a large pot, sauté the chopped onion in olive oil until soft. \n2. Add the frozen peas, salt, pepper, and water. Simmer for 5 minutes. \n3. Remove half of the peas and blend until smooth. Pour it back in! This is the secret to how to cook peas so they become a rich sauce. \n4. Add your Ditalini and cook for 10 minutes, stirring frequently. Add a splash of water if it gets too dry. \n5. Turn off the heat. Stir in the Pecorino Romano until it creates a thick, cheesy sauce.\n\n⭐ Video Chapters \n0:00 What Italians Actually Eat at Home \n0:29 Start with a Base of Onions\n0:43 Everyone has Frozen Peas in the Freezer\n1:30 The Creamy Secret \n2:29 One-Pot Cooking \n4:12 The Cheese Finish \n4:50 Preview of Cream in the Pan\n5:07 Plating\n5:48 Giovanni\n\nWhy You’ll Love This Recipe:\n✅ Authentic Italian Comfort: This isn't restaurant food; it’s the real-life soul food of Italy. \n✅ True Mediterranean Diet: A perfect balance of plant-based protein and carbs that keeps you full and healthy. \n✅ Zero-Stress Cooking: One pot, minimal ingredients, and only 20 minutes from start to finish.\n\nComment Below:\nI actually wasn't crazy about this as a kid, but now I absolutely love it! What about you? Was there a meal you hated growing up that you love now? \nLet me know in the comments! 👇🫛🍝\n\nFollow Giovanni:\n▶ YOUTUBE https://www.youtube.com/@giovannisiracusaa\n▶ INSTAGRAM https://www.instagram.com/giovannisiracusaa/\n▶ FACEBOOK https://www.facebook.com/giovannisiracusaa/\n▶ TIKTOK https://www.tiktok.com/@giovannisiracusaa\n\n🍳Tools Used in this Video (links may earn commission).\nPots & Pans: https://rstr.co/caraway/43648 (10% off Code: UNPEZZODITALIA10)\nInduction Cooktop: https://amzn.to/4sA3pr1\nKettle: https://amzn.to/3Lo7UnP\nImmersion Hand Blender: https://amzn.to/4soFtpH\n\n#pasta #peas #italianfood",
        "age": "",
        "meta_url": {
          "profile_image": "https://yt3.ggpht.com/M5PhMFdGMX0ohrzdyh7LOzW7z0sjgzaQLnGwfEGN_V9W5HJAkHDLL_z7UAgXJnDcYKWSFjXBwA=s800-c-k-c0x00ffffff-no-rj"
        },
        "thumbnail": {
          "original": "https://i.ytimg.com/vi/8NFqnhWHxNY/maxresdefault.jpg"
        },
        "viewCount": 1360467,
        "likeCount": 44223,
        "channelTitle": "Giovanni Siracusa",
        "publishedAt": "2026-01-31T16:02:36Z",
        "duration": "PT6M41S"
      },
      {
        "title": "5 Easy Dinners You Can Cook in 30 Minutes | Allrecipes",
        "url": "https://www.youtube.com/watch?v=06JDURvWPNI",
        "description": "Short on time but still want a satisfying, homemade dinner? In this video, Nicole shares five easy dinners you can cook in just 30 minutes—perfect for busy weeknights when you need something fast, comforting, and full of flavor. These recipes are designed to keep prep simple, cook times short, and cleanup minimal, without sacrificing that “real dinner” feeling.\n\nNicole starts with a creamy Chicken Pot Pasta that delivers all the cozy vibes of a pot pie in a quicker, weeknight-ready format. Next up is a Chicken Chip Bake, a Mexican-inspired dinner made with tortilla chips, pinto beans, and bold flavors that come together fast. For something crispy and craveable, she makes Air Fryer Bang Bang Salmon, finished with a sweet-spicy sauce that feels restaurant-worthy. Then it’s comfort food at its finest with Poor Man’s Steak, a budget-friendly classic made with tender pork chops. Nicole wraps things up with Cuban-Style Picadillo, a savory, slightly sweet ground-meat dish that’s packed with flavor and perfect for spooning over rice.\n\nWhether you’re cooking for your family or just trying to get dinner on the table without stress, these quick and easy meals prove that great food doesn’t have to take all night.\n\nTimestamps:\n0:00 – 5 Easy 30-Minute Dinners\n0:19 – Chicken Pot Pasta\n3:56 – Chicken Chip Bake\n7:00 – Air Fryer Bang Bang Salmon\n9:22 – Poor Man’s Steak (with Pork Chops)\n14:23 – Cuban-Style Picadillo\n\nGet the recipes here:\n\nChicken Pot Pasta: https://www.allrecipes.com/chicken-pot-pasta-recipe-11887356\nChicken Chip Bake: https://www.allrecipes.com/chicken-chip-bake-recipe-11883909\nAir Fryer Bang Bang Salmon: https://www.allrecipes.com/recipe/8340433/air-fried-bang-bang-salmon/\nPoor Man’s Steak (with Pork Chops): https://www.allrecipes.com/pork-chop-steaks-recipe-11887332\nCuban-Style Picadillo: https://www.allrecipes.com/recipe/220164/classic-cuban-style-picadillo/\n_________\nAllrecipes Magazine is now available!\nU.S. subscribers, subscribe here: http://armagazine.com/subscribenow\nCanadian subscribers, subscribe here: http://themeredithstore.ca/p-282-allrecipes-subscription.aspx\nFacebook: http://www.facebook.com/Allrecipes\nInstagram: https://www.instagram.com/allrecipes/\nPinterest: https://www.pinterest.com/allrecipes/\nTikTok: https://www.tiktok.com/@allrecipes",
        "age": "",
        "meta_url": {
          "profile_image": "https://yt3.ggpht.com/ytc/AIdro_kbMMelLXlcwPGEbCBEoHi8CWZ5LYKW0cBX-3zEFIXIegGc=s800-c-k-c0x00ffffff-no-rj"
        },
        "thumbnail": {
          "original": "https://i.ytimg.com/vi/06JDURvWPNI/maxresdefault.jpg"
        },
        "viewCount": 845206,
        "likeCount": 25128,
        "channelTitle": "Allrecipes",
        "publishedAt": "2026-01-27T17:00:01Z",
        "duration": "PT18M24S"
      },
      {
        "title": "Three Weeknight Pastas perfect for whatever mood you are in.",
        "url": "https://www.youtube.com/watch?v=aVAN4_pWCwY",
        "description": "Want to become a more confident and creative home cook? Check out our Cook Well app: https://apps.apple.com/us/app/cook-well-for-home-cooks/id6748092442\n\nhttps://play.google.com/store/apps/details?id=com.cookwell.app&hl=en_US In today's video, I'm covering three weeknight pasta dishes, and each one has a unique selling point depending on what mood you are in (fast, healthy, comforting) the first pasta recipe is from this Sunday's newsletter, sign up here to get it ➡ https://www.cookwell.com/newsletter\n\n📃 RECIPE Link(s):\nCreamy Tomato & Sausage Pasta - https://www.ethanchlebowski.com/cooking-techniques-recipes/creamy-sausage-pasta-salsiccia-e-panna\nHealthier White Cheddar Mac & Cheese - https://www.ethanchlebowski.com/cooking-techniques-recipes/healthier-chicken-white-cheddar-mac-amp-cheese-hj3pl\n\n🧅  Join the Pickled Onion Club ➡ https://community.ethanchlebowski.com/\n🍳  The Mouthful newsletter (free)➡ https://www.cookwell.com/newsletter\n\n📸 Instagram ➔ https://www.instagram.com/echleb/\n🎚 TikTok ➔ https://www.tiktok.com/@ethanchlebowski\n🐣 Twitter ➔ https://twitter.com/EthanChleb\n\nUSEFUL KITCHEN GEAR\n\n🌡Thermapen Thermometer: https://alnk.to/6bSXCCG\n🍳 Made In Wok I use: https://bit.ly/3rWUzWX\n🥌 Budget Whetstone for sharpening: https://geni.us/1k6kComboWhetstone\n🧂 Salt Pig: https://geni.us/SaltContainer\n⚖ Scale: https://geni.us/FoodScale\n🍴 Budget 8-inch Chef's knife: https://geni.us/BudgetChefKnife\n🔪 Nicer 8-inch Chef Knife: https://geni.us/TojiroChefKnife\n🧲 Magnetic Knife Rack: https://geni.us/MagneticKnifeRack\n🥘 Cast iron griddle: https://geni.us/TheCastIronGriddle\n📄 Baking Sheet: https://geni.us/NordicBakingSheet\n🛒 Wire Rack: https://geni.us/WireRack\n🍳 Saucepan: https://geni.us/Saucepan\n🪓 Woodcutting board: https://geni.us/SolidWoodCuttingBoard\n\n⏱ TIMESTAMPS:\n0:00 Intro\n0:55 The Fastest Pasta\n4:30 The Healthy Pasta\n7:41 The Best Tasting Pasta\n\n🎵 Music by Epidemic Sound (free 30-day trial - Affiliate): http://share.epidemicsound.com/33cnNZ\n\nMISC. DETAILS\nMusic: Provided by Epidemic Sound\nFilmed on: Sony a6600 & Sony A7C\nVoice recorded on Shure MV7\nEdited in: Premiere Pro\n\nAffiliate Disclosure:\nEthan is a participant in the Amazon Services LLC Associates Program, an affiliate advertising program designed to provide a means for us to earn fees by linking to [Amazon.com](http://amazon.com/) and affiliated sites.",
        "age": "",
        "meta_url": {
          "profile_image": "https://yt3.ggpht.com/ytc/AIdro_nASBGz3OXASRVham6ZgSHJrheFcXNKHtI86bw0QeA9ENc=s800-c-k-c0x00ffffff-no-rj"
        },
        "thumbnail": {
          "original": "https://i.ytimg.com/vi/aVAN4_pWCwY/maxresdefault.jpg"
        },
        "viewCount": 749432,
        "likeCount": 24648,
        "channelTitle": "Ethan Chlebowski",
        "publishedAt": "2022-12-18T16:00:00Z",
        "duration": "PT11M20S"
      }
    ]
  },
  {
    "id": "store-example-videos-search-3",
    "query": "Beginner morning yoga routine",
    "query_translation_key": "settings.app_store_examples.videos.search.3",
    "provider": "Brave Search",
    "status": "finished",
    "results": [
      {
        "title": "10 minute Morning Yoga for Beginners",
        "url": "https://www.youtube.com/watch?v=VaoV1PrYft4",
        "description": "Join me in this quick and simple 10 minute morning yoga for beginners routine to stretch out stiffness and energize for a great day. 💙  Get MORE in the SarahBethYoga APP https://members.sarahbethyoga.com/orders/customer_info?o=133542 (exclusive discount!)\n\nYou'll also like my ▶ BEGINNER YOGA PLAYLIST: http://bit.ly/sbyBeginners with NEW, updated, and much better quality beginner yoga videos. \n\nCHAPTERS:\n00:00 welcome\n00:12 Seated spinal waves\n00:50 Side body stretches\n01:40 Seated twist\n02:20 Chest & shoulder stretch\n02:56 Calf stretches\n03:45 Downdog\n04:41 Forward Fold\n05:10 Unroll up to standing\n05:35 Hip circles\n06:40 Mountain pose\n07:00 Halfway lift\n07:15 Mini flow\n08:00 Tabletop twists\n09:00 Child's pose\n09:50 ▶ BEGINNER YOGA PLAYLIST: http://bit.ly/sbyBeginners\n\nWELCOME to your \"Modern Day Yoga\" YouTube channel by Sarah Beth Yoga where you can find clear & fuss-free yoga videos ranging from short 10 minute yoga routines to longer 30 minute yoga practices for all levels to help you get stronger, happier & healthier. 😍 SUBSCRIBE for MORE free yoga: http://bit.ly/sarahbethyoga  \n\n🔸🔸🔸🔸🔸🔸🔸🔸🔸🔸🔸🔸🔸🔸🔸🔸🔸\nMORE YOGA: \n\n✨SarahBethYoga APP ✨\nhttps://www.sarahbethyoga.com/join\n\n💙 DOWNLOAD & Take your favorite yoga videos with you in the SarahBethYoga App and get the entire SBY library of 700+ ad-free & downloadable yoga videos, +250 exclusive videos, classes & calendars including:\n•Beginner, Prenatal & Tone Yoga Programs\n•40+ full-length 45 minute & 60 minute yoga classes\n•40+ monthly yoga calendars\n•Yoga Pose Breakdowns\n•Yoga Tips series\n•Live calls in our private Facebook group\n•Printable PDF guides like: What is Yoga Guide, How to Yoga Guide, Yoga Lingo Guide\n•Access on all devices: iOS, Android, Desktop, Roku, AppleTV, FireTV\n\nLearn more about the SarahBethYoga APP & join us at: https://www.sarahbethyoga.com/join\n\n▶ BEGINNER YOGA PLAYLIST: http://bit.ly/sbyBeginners\n▶ MORNING YOGA PLAYLIST: http://bit.ly/sbyMorning\n\n💙  Facebook: /sarahbethyoga\n💜  Instagram: @sarahbethyoga\n\n📚 Get my NEW book \"TRAUMA ALCHEMY\": https://a.co/d/5DLhPYc\n\n🔸🔸🔸🔸🔸🔸🔸🔸🔸🔸🔸🔸🔸🔸🔸🔸🔸\nYOGA PROPS, YTT, RETREATS:\n\nCheck out my recommendations for yoga mats, bolster, blocks, yoga teacher training, retreats and more in the SarahBethYoga Resource Center: https://www.sarahbethyoga.com/resource-center\n\n🔸🔸🔸🔸🔸🔸🔸🔸🔸🔸🔸🔸🔸🔸🔸🔸🔸\nPlease mail letters, packages & PR to: \n\nSarahBethYoga\nP.O. Box 631594\nHighlands Ranch, CO 80163\n\n🔸🔸🔸🔸🔸🔸🔸🔸🔸🔸🔸🔸🔸🔸🔸🔸🔸\n\nDisclaimer: Some links may be affiliate links which help support Sarah Beth to create content, however Sarah Beth only promotes products she truly likes and all opinions are her own. Sarah Beth from Sarah Beth Yoga LLC strongly recommends that you consult with your physician before beginning any exercise program. You should be in good physical condition and be able to participate in the exercise. You should understand that when participating in any exercise or exercise program, there is the possibility of physical injury. If you engage in this exercise or exercise program, you agree that you do so at your own risk, are voluntarily participating in these activities, assume all risk of injury to yourself, and agree to release and discharge\n\n#10minuteyoga #morningyoga #yogaforbeginners\n\nBeginner yoga, beginner morning yoga, yoga for beginners morning, yoga for beginners, yoga for absolute beginners, morning yoga for beginners, yoga for complete beginners, 10 minute yoga, 10 minute morning yoga, 10 minute yoga for beginners, 10 minute beginner yoga,",
        "age": "",
        "meta_url": {
          "profile_image": "https://yt3.ggpht.com/5HigdOXL4GLPimfb5W1TjsX7ziMRqzUmr2wfzAQwTkqYpIW9uH-jA-VeiI1Yhl58NXGaz5eiog=s800-c-k-c0x00ffffff-no-rj"
        },
        "thumbnail": {
          "original": "https://i.ytimg.com/vi/VaoV1PrYft4/maxresdefault.jpg"
        },
        "viewCount": 30292178,
        "likeCount": 339478,
        "channelTitle": "SarahBethYoga",
        "publishedAt": "2017-02-10T14:52:53Z",
        "duration": "PT10M"
      },
      {
        "title": "10 Minute Morning Stretch for every day | Simple routine to wake up & feel good",
        "url": "https://www.youtube.com/watch?v=ihba9Lw0tv4",
        "description": "Welcome to your Daily Morning Stretching Session. A beginner friendly 10 minute routine, which helps you to wake up, energize and simply feel good! This session is your perfect Miracle Morning Routine for a mindful start into your day. We combine yoga inspired movements, with mobility exercises and mindful breathing to wrap up our session!\n\nDo your body and mind a favour and start your day off with a little bit of daily movement. Its only 10 minutes, but believe me, it will make a huge different and you will soon feel improvements (if you do this regularly).\nEnjoy your dose of flexibility & mobility and have an amazing start into the day!\n\n\n\nIn addition to my German voice-over-videos, I will be producing more music-only stretching and fitness content in the future, so everybody can join! If you have any video requests, please let me know in the comments.\n\nThank you for practising with me!\nMady\n\n\n********************************\n\n\nNO ADS!\nAs in all of my sessions, I do not put any ads within the video. So you won’t be interrupted in the middle of your workout.\n\n\nKEINE WERBUNG!\nWie in allen meinen Einheiten, schalte ich innerhalb der Videos keine Werbung! Ihr werdet also nicht mitten im Workout unterbrochen.\n\n\nDiese Yoga-Einheit könnt ihr ganz prima im Anschluss absolvieren:\nhttps://youtu.be/dJxnU9sOh6Q\n\n\nPS: Keine Sorge ihr Lieben, natürlich wird es auch weiterhin „gesprochene“ Videos geben. Das eine schließt das andere ja nicht aus und der nächste Yoga-Flow ist schon in Planung ;-) \n\n\n\n********************************\n\n\n\nDas ist meine Matte: http://amzn.to/2mo8NNr *\n(und mit Abstand meine absolute Nummer 1)\n\nDu magst die Matte lieber in einem komplett nachhaltigen Shop kaufen?\nSchau mal hier:\nhttps://tidd.ly/3i33gXO *\n\nMein Meditationskissen:\nhttps://tidd.ly/3aGk84n *\n\n\n\n********************************\n\n\n\nMORE MUSIC-ONLY SESSIONS:\n\n15 MIN DAILY STRETCH:\nhttps://youtu.be/g_tea8ZNk5A\n\n\nNECK & SHOULDER STRETCH:\nhttps://youtu.be/s-7lyvblFNI\n\n\nBACK PAIN RELIEF STRETCHES:\nhttps://youtu.be/2eA2Koq6pTI\n\n\n\n\n********************************\n\n\n\nEQUIPMENT:\n\nMeine liebste Matte: \nhttp://amzn.to/2mo8NNr *\n\nMeine Vlogging Cam: \nhttp://amzn.to/1GsIWWo *\n\nMein Make Up 100% Bio- bzw Naturkosmetik\nhttp://amzn.to/1LtYY89 *\n\nMein neuer Mixer (macht die besten Smoothies ever!)\nhttp://amzn.to/2n4BayW *\n\n\n\n\n\n********************************\n\n\nMUSIK: www.epidemicsound.com\n\n\n********************************\n\n\n\n\nFür tägliche Inspiration YOGA, TRAVEL & LIFESTYLE :\n\nInstagram : https://instagram.com/madymorrison/\nFacebook: https://www.facebook.com/morrison.mady\nBlog: http://www.madymorrison.com\n\n\n\n* das ist ein Affiliate Link. Wenn du über diesen Link etwas kaufst, erhalte ich eine kleine Provision. Am Preis verändert sich für dich rein gar nichts!! So kannst du diesen Kanal unterstützen und hilfst mir weiterhin kostenlose Aktionen und Videos für euch zu erstellen. Vielen Dank für deinen Support!",
        "age": "",
        "meta_url": {
          "profile_image": "https://yt3.ggpht.com/ytc/AIdro_myyDZtX1Ueod8MSB3WcWMNOF1Kv9v7c9W6wgY6M7PN6AQ=s800-c-k-c0x00ffffff-no-rj"
        },
        "thumbnail": {
          "original": "https://i.ytimg.com/vi/ihba9Lw0tv4/maxresdefault.jpg"
        },
        "viewCount": 17634230,
        "likeCount": 227096,
        "channelTitle": "Mady Morrison",
        "publishedAt": "2022-03-13T06:00:20Z",
        "duration": "PT11M33S"
      },
      {
        "title": "10 min Morning Yoga Stretch for Beginners - Energy Boost Yoga",
        "url": "https://www.youtube.com/watch?v=T41mYCmtWls",
        "description": "Enjoy this energy boosting morning yoga flow great for beginners! No props needed.\n🌞 Join the 30-Day Yoga & Pilates Morning Challenge: https://bit.ly/30dayyogalates\n✅FREE WEEKLY YOGA CLASSES http://bit.ly/ywkassandra\n\nHey yogis, you guys keep asking for more 10 minute yoga classes so I'm serving up a good one today. :) Here's a brand new 10 minute morning yoga stretch, great to do when you've just gotten out of bed. I also snuck in a bit of strengthening yoga poses in here to give you the boost of energy you need most in the early hours of the day.\n\nNo props necessary for this class but if you have a block at home you can always grab it to make some poses more accessible. This is a full body morning yoga stretch that will target all the aches and pains you may have accumulated during the night. Enjoy!\n\n😍 MORE 10 MINUTE YOGA 😍👉 https://www.youtube.com/playlist?list=PLW0v0k7UCVrkh5WZyHu0d0fWnaNgbmQTw\n\nThis class was filmed at Elevate Yoga in Ottawa where I teach! Come take a class with me :) https://elevateyoga.ca/\n\n\nThanks for watching,\nKassandra\nhttp://www.yogawithkassandra.com\nhttps://instagram.com/yoga_with_kassandra\n\n\n📱 MY MOBILE APP 📱 Stream or download more than 1000+ classes, use the in-app calendar to track and schedule classes, new exclusive challenges, classes and programs added every month ❤ FREE TO DOWNLOAD ❤ https://yogawithkassandra-members.com/\n\n\nFREE YOGA CHALLENGES\n🌞 30 day Morning Yoga Challenge http://bit.ly/morning30days\n🌛 30 day Evening Yoga Challenge: http://bit.ly/bedtime30\n🧘 7 day Yoga & Meditation Challenge: http://bit.ly/ywk7day\n🤸 30 day Flexible Body, Flexible Mind Challenge: https://bit.ly/flexbodymind\n💪 30-Day Yoga & Pilates Morning Challenge: https://bit.ly/30dayyogalates\n\n\n🛍 SHOP MY MERCHANDISE, BOOKS & ONLINE COURSES 🧘👉 https://bit.ly/ywkshop\n\n\n🎓 STUDY WITH ME 🕉 ONLINE TEACHER TRAININGS: https://bit.ly/yttcourses\n\n\n🛒 SHOP MY AMAZON FAVORITES 🛍 https://amzn.to/4kKJFMW\n\n\n✅ SUBSCRIBE TO SUPPORT FREE YOGA ON THE INTERNET http://bit.ly/ywkassandra\n\n\nYoga with Kassandra - Disclaimer\nPlease consult with your physician before beginning any exercise program. By participating in this exercise or exercise program, you agree that you do so at your own risk, are voluntarily participating in these activities, assume all risk of injury to yourself, and agree to release and discharge Yoga with Kassandra from any and all claims or causes of action, known or unknown, arising out of Yoga with Kassandra’s negligence.#10minyoga #morningyoga #yogawithkassandra",
        "age": "",
        "meta_url": {
          "profile_image": "https://yt3.ggpht.com/WhS9NJxvfykEmhpyPYw0d14bA3hAKBzbey_PZcKoVX9zygqmduKATnH_EL1q_W4en_XVAooomKI=s800-c-k-c0x00ffffff-no-rj"
        },
        "thumbnail": {
          "original": "https://i.ytimg.com/vi/T41mYCmtWls/sddefault.jpg"
        },
        "viewCount": 9272731,
        "likeCount": 196625,
        "channelTitle": "Yoga with Kassandra",
        "publishedAt": "2019-11-07T11:15:11Z",
        "duration": "PT13M30S"
      },
      {
        "title": "20 Minute Morning Yoga Flow | Daily Yoga Routine - Stretch + Strengthen",
        "url": "https://www.youtube.com/watch?v=hnrkkvx4d50",
        "description": "This is a 20 minute full body yoga flow aimed to stretch and strengthen your body and give yourself an energy boost in the morning! Perfect sequence for all levels. Practice this flow regularly and incorporate it into your morning routine.\nNo props needed. See you on the mat! \n\nWith gratitude,\nJess\n\nPS--  Practice more classes like this on the Jess Yoga app, which includes over 500+ classes, courses, and challenges. \n 🌟 USE THE CODE 'YT15' FOR 15% OFF YOUR JESS YOGA MEMBERSHIP! 🌟\nhttps://jessyogaapp.web.app/landing-page\n\n📲🪷 MOBILE APP \nJESS YOGA available worldwide on iOS & Android. \nPractice with me ad-free & gain access to exclusive yoga classes + programs. \nPlay videos on your desktop, TV, phone, or tablet.\n\n\nFAVORITES ✨ \nYoga Mat:\nLiforme (Use code 'JESSICARICHBURG' for 10% off)\nhttp://bit.ly/2uH0xNf\n\nActivewear:\nStudio Kolektif Organic Yogawear (Use code 'JESSICARICHBURG' for 15% off)\nhttps://bit.ly/2WDxXtr\n\nJournal:\nWeekly Reset Planner + Artist of Life Workbook from Lavendaire\nhttps://shop.lavendaire.com/JESSICA10 (Use code 'JESSICA10' for 10% off)\n\n\nDONATE 🦋\nDonations to this channel allows me to keep creating new content + keeps yoga free & accessible to all.  \nIf you'd like to donate you can click the link below:\nhttps://bit.ly/31WdAZE\nThank you for supporting my work! \n\n\nCONNECT 🙏 \nBlog: https://jessicarichburgyoga.com\nInstagram: https://instagram.com/Jessicarichburg\nFacebook: https://www.facebook.com/jessicarichburgyoga/\n💌 Sign up for my newsletter:\nhttps://jessicarichburgyoga.com/newsletter/\n\n- \n\nDISCLAIMER\nThe information and practices on this website are not meant to diagnose, treat or cure any illness and and should not be used as a substitute for professional medical care. As with any exercise program, you take the risk of personal injury when you practice yoga. Please be mindful and listen to your body. By voluntarily participating in these practices, you acknowledge this risk and release Jessica Richburg from any liability. You are responsible for your own body's well being. Please consult with your physician prior to beginning exercise.\n\nMUSIC \nhttps://www.youtube.com/audiolibrary/\nPeaceful Mind by Astron\nSong Of Sadhana by Jesse Gallagher\nVinyasa by Chris Haugen \nKrishna's Calliope by Jesse Gallagher\nSpirit of Fire by Jesse Gallagher",
        "age": "",
        "meta_url": {
          "profile_image": "https://yt3.ggpht.com/aG-Z_Hu-F6_1LKYUuBfR8wRSYAUBAJaY2_tpeGNDykiEbuSft3sz6r2Q9RWfup6ugVpplNdIKA=s800-c-k-c0x00ffffff-no-rj"
        },
        "thumbnail": {
          "original": "https://i.ytimg.com/vi/hnrkkvx4d50/maxresdefault.jpg"
        },
        "viewCount": 4763567,
        "likeCount": 70318,
        "channelTitle": "Jess Yoga",
        "publishedAt": "2020-06-10T16:07:19Z",
        "duration": "PT19M15S"
      }
    ]
  }
]

export default examples;
