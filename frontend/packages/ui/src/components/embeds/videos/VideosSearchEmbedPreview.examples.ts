/**
 * App-store examples for the videos/search skill.
 *
 * Captured from real Brave video search responses, trimmed to 4 results per query.
 *
 * Each example includes an optional `query_translation_key` that
 * SkillExamplesSection resolves via the i18n store at render time, so
 * the card label is localised while the raw provider data stays
 * authentic.
 */

export interface VideosSearchStoreExample {
  id: string;
  query: string;
  query_translation_key: string;
  provider: string;
  status: 'finished';
  results: Array<Record<string, unknown>>;
}

const examples: VideosSearchStoreExample[] = [
  {
    "id": "store-example-videos-search-1",
    "query": "svelte 5 runes tutorial",
    "query_translation_key": "app_store_examples.videos.search.1",
    "provider": "Brave Search",
    "status": "finished",
    "results": [
      {
        "title": "JavaScript framework reinvents itself… Did \"runes\" just ruin Svelte?",
        "url": "https://www.youtube.com/watch?v=aYyZUDFZTrM",
        "description": "Svelte 5 was released this week with a new developer experience via a feature called \"Runes\". Learn the basics of Svelte Runes compare them to other JavaScript frameworks like React.js, Vue, Angular, and more.  \n\nUse Discount code GOTRUNES and take 30% off Fireship PRO\nhttps://fireship.io/pro\n\n#programming #webdevelopment #thecodereport \n\n💬 Chat with Me on Discord\n\nhttps://discord.gg/fireship\n\n🔗 Resources\n\nFull Svelte Course https://fireship.io/courses/sveltekit/\nSvelteKit in 100 Seconds https://youtu.be/H1eEFfAkIik\nWordPress Drama Overview https://youtu.be/mc5P_082bvY\n\n📚 Chapters\n\n🔥 Get More Content - Upgrade to PRO\n\nUpgrade at https://fireship.io/pro\nUse code YT25 for 25% off PRO access \n\n🎨 My Editor Settings\n\n- Atom One Dark \n- vscode-icons\n- Fira Code Font\n\n🔖 Topics Covered\n\n- Svelte 5 First Look\n- Svelte 5 quick tutorial\n- What are Svelte Runes?\n- Svelte vs React\n- Trends in JavaScript frameworks",
        "age": "",
        "meta_url": {
          "profile_image": "https://yt3.ggpht.com/3fPNbkf_xPyCleq77ZhcxyeorY97NtMHVNUbaAON_RBDH9ydL4hJkjxC8x_4mpuopkB8oI7Ct6Y=s800-c-k-c0x00ffffff-no-rj"
        },
        "thumbnail": {
          "original": "https://i.ytimg.com/vi/aYyZUDFZTrM/maxresdefault.jpg"
        },
        "viewCount": 551437,
        "likeCount": 24513,
        "channelTitle": "Fireship",
        "publishedAt": "2024-10-24T19:33:42Z",
        "duration": "PT4M19S"
      },
      {
        "title": "Svelte 5 Preview | Runes",
        "url": "https://www.youtube.com/watch?v=Jza-pMdG5ms",
        "description": "Recorded live on twitch, GET IN \n\nhttps://twitch.tv/ThePrimeagen\n\nReviewed article: https://svelte.dev/blog/runes\n\nMY MAIN YT CHANNEL: Has well edited engineering videos\nhttps://youtube.com/ThePrimeagen\n\nDiscord\nhttps://discord.gg/ThePrimeagen\n\n\nHave something for me to read or react to?: https://www.reddit.com/r/ThePrimeagenReact/\n\nHey I am sponsored by Turso, an edge database.  I think they are pretty neet.  Give them a try for free and if you want you can get a decent amount off (the free tier is the best (better than planetscale or any other))\nhttps://turso.tech/deeznuts",
        "age": "",
        "meta_url": {
          "profile_image": "https://yt3.ggpht.com/Eu_xR4JfLlrruwj1lrmfDiOpe8GARBs8M0hgQ6NsGhQ0qC8S-po9HEHw1W21sPN2BHO6EHXrSwM=s800-c-k-c0x00ffffff-no-rj"
        },
        "thumbnail": {
          "original": "https://i.ytimg.com/vi/Jza-pMdG5ms/maxresdefault.jpg"
        },
        "viewCount": 87430,
        "likeCount": 2319,
        "channelTitle": "The PrimeTime",
        "publishedAt": "2023-09-21T12:00:26Z",
        "duration": "PT12M40S"
      },
      {
        "title": "The Svelte 5 Reactivity Guide",
        "url": "https://www.youtube.com/watch?v=tErKyuUTzsM",
        "description": "Svelte 5 introduces a new fine-grained universal reactivity system named runes which uses signals under the hood.\n\n🔴 Patreon: https://www.patreon.com/joyofcode\n 𝕏 Twitter: https://twitter.com/joyofcodedev\n💬 Discord: https://discord.com/invite/k6ZpwAKwwZ\n🔥 Uses:  https://www.joyofcode.xyz/uses\n\n🔖 Timestamps\n\n0:00 Intro\n0:07 Rethinking Reactivity\n0:21 Svelte 3\n3:47 Svelte Runes\n8:28 Universal Reactivity\n10:08 Deeply Nested Reactivity\n14:26 Reactivity Patterns\n16:13 Props\n19:05 Inspecting State\n20:09 Svelte Ecosystem\n\n#joyofcode #sveltekit #svelte",
        "age": "",
        "meta_url": {
          "profile_image": "https://yt3.ggpht.com/6sy2xPMxXUUk3yXvpCoZrziuFs8sRD75NRZn-zSxkNHcbwpDCJ4wOKmw-WyEoP3GeIVWaTNzOg=s800-c-k-c0x00ffffff-no-rj"
        },
        "thumbnail": {
          "original": "https://i.ytimg.com/vi/tErKyuUTzsM/maxresdefault.jpg"
        },
        "viewCount": 52530,
        "likeCount": 1553,
        "channelTitle": "Joy of Code",
        "publishedAt": "2024-06-21T20:00:32Z",
        "duration": "PT21M41S"
      },
      {
        "title": "Svelte 5 runes: what's the deal with getters and setters?",
        "url": "https://www.youtube.com/watch?v=NR8L5m73dtE&pp=ygUNI2V4cG9ydHZhbHVlcw%3D%3D",
        "description": "Context: https://svelte.dev/blog/runes",
        "age": "",
        "meta_url": {
          "profile_image": "https://yt3.ggpht.com/ytc/AIdro_lrZAc7AfMPRhoj2LOtDcr_G65UF93RKa2pn3Gm_TBWQWg=s800-c-k-c0x00ffffff-no-rj"
        },
        "thumbnail": {
          "original": "https://i.ytimg.com/vi/NR8L5m73dtE/maxresdefault.jpg"
        },
        "viewCount": 48276,
        "likeCount": 2485,
        "channelTitle": "Rich Harris",
        "publishedAt": "2023-09-23T21:22:34Z",
        "duration": "PT11M22S"
      }
    ]
  },
  {
    "id": "store-example-videos-search-2",
    "query": "cooking perfect pasta carbonara",
    "query_translation_key": "app_store_examples.videos.search.2",
    "provider": "Brave Search",
    "status": "finished",
    "results": [
      {
        "title": "Real Spaghetti Carbonara | Antonio Carluccio",
        "url": "https://www.youtube.com/watch?v=3AAdKl1UYZs",
        "description": "RIP dear Antonio. You will be truly missed.  X\n\nThe legendary Antonio Carluccio finally makes his debut on Food Tube! We are honoured to have this incredible chef, author, restauranteur and old friend of Gennaro Contaldo share with us - and you - his authentic Italian carbonara recipe. So simple. So tasty. \n\nWhat's your favourite pasta recipe Food Tubers? Any other great tips or methods for making this most classic of dishes? Please get in touch in the comments box below.\n\nWould you like to see more of Antonio on the channel? If you shout loud enough we'll ask him very nicely to do some more videos!\n\nRecipe here: http://goo.gl/QuRCzK\n\nIn the meantime you can read more of his fantastic pasta recipes in his new book: http://goo.gl/509kJ3\n\nAnd you can read more great recipes in the Two Greedy Italians book written with Food Tube's very own Gennaro Contaldo: http://goo.gl/yLNlkJ\n\nLinks from the video:\nPerfect Spaghetti Bolognese | http://goo.gl/4solzy\nMore Food Tube videos | http://goo.gl/D9NMja\n\nFor more nutrition info, click here: http://jamieol.com/D3JimM\n\nJamie Oliver's Food Tube | http://goo.gl/EdJ0vK\nSubscribe to Food Tube | http://goo.gl/v0tQr\nTwitter: https://twitter.com/JamiesFoodTube\nTumblr: http://jamieoliverfoodtube.tumblr.com/\nFacebook | http://goo.gl/7R0xdh\nMore great recipes | http://www.jamieoliver.com\n\n#FOODTUBE\n\nx",
        "age": "",
        "meta_url": {
          "profile_image": "https://yt3.ggpht.com/ZyXW1QZjuQ79W_pzUbQ2VIw-ljhbOFMmOx8IAAUg4gNt-91JlWW0L_1dxX_S0vfYN5miqLP0DA=s800-c-k-c0x00ffffff-no-rj"
        },
        "thumbnail": {
          "original": "https://i.ytimg.com/vi/3AAdKl1UYZs/maxresdefault.jpg"
        },
        "viewCount": 24713751,
        "likeCount": 371658,
        "channelTitle": "Jamie Oliver",
        "publishedAt": "2014-03-27T19:30:01Z",
        "duration": "PT5M13S"
      },
      {
        "title": "How To Cook The Perfect Pasta | Gordon Ramsay",
        "url": "https://www.youtube.com/watch?v=UYhKDweME3A",
        "description": "Top tips on how to how to cook angel hair pasta - with principles that you can apply to cooking any shape. If you have any others, let us know - always keen to learn. \n\n#GordonRamsay #Cooking \n\nGordon Ramsay's Ultimate Fit Food/Healthy, Lean and Fit – http://po.st/REpVfP\n\nFollow Gordon:\nText him: +1 (310) 620-6468\nInstagram: http://www.instagram.com/gordongram\nTwitter: http://www.twitter.com/gordonramsay  \nFacebook: http://www.facebook.com/GordonRamsay\n\nIf you liked this clip check out the rest of Gordon's channels:\n\nhttp://www.youtube.com/gordonramsay\nhttp://www.youtube.com/kitchennightmares\nhttp://www.youtube.com/thefword\"",
        "age": "",
        "meta_url": {
          "profile_image": "https://yt3.ggpht.com/iu8M-gugkNvz-lHxC1sMEfAlL7ONWbP91c5SM9bb98oCJAcYUl0HIAMZFFR2Dd-soGag1Y1y8A=s800-c-k-c0x00ffffff-no-rj"
        },
        "thumbnail": {
          "original": "https://i.ytimg.com/vi/UYhKDweME3A/maxresdefault.jpg"
        },
        "viewCount": 11688354,
        "likeCount": 130944,
        "channelTitle": "Gordon Ramsay",
        "publishedAt": "2014-01-09T17:00:02Z",
        "duration": "PT1M32S"
      },
      {
        "title": "How to Make SPAGHETTI CARBONARA (Approved by Romans)",
        "url": "https://www.youtube.com/watch?v=AvO8UPbIH30",
        "description": "Spaghetti carbonara recipe – original and approved by Romans! Before we start, the number one rule is simple –REAL SPAGHETTI CARBONARA RECIPE IS MADE WITH EGGS, NOT CREAM!\n\nCombine fresh eggs, with crispy guanciale, salty pecorino cheese and pepper to create the perfect, classic Roman pasta dish, Carbonara. In this video recipe, I tested out my traditional version with some locals from Rome and they loved it! Make this classic the right way and I promise, your tastebuds will thank you.\n\n#spaghetticarbonara #howtomakespaghetticarbonara #carbonara\n\n==========================================\n\nIntroducing My Debut Cookbook: Authentic Italian \nOrder your copy from anywhere in the world and bring Italy into your home. Find your local stockist:\n👉 https://www.vincenzosplate.com/authentic-italian-cookbook/\n\n==========================================\n\n👨🍳🧑🍳Join Vincenzo's Plate Italian Cooking Academy and Became an Italian Food Ambassador: https://academy.vincenzosplate.com/cooking-academy\n\n📺SUBSCRIBE TO MY YOUTUBE CHANNEL (IT’S FREEEEEE ;-) http://bit.ly/SubscribeToMyYOUTUBEchannel\n\n📖Share it with your FOODIE friends on FACEBOOK  \n\n🌍Get the recipe on my website\n\n🍝Check out my website for full recipes and to follow my blog: http://vincenzosplate.com/\n\nJoin my Sydney Cooking Classes: http://www.vincenzosplate.com/cooking-class-in-sydney/\n\nDownload my Mobile App https://appsto.re/au/nJ4Pgb.i\n\nBuy Vincenzo’s Plate Apron on: http://www.vincenzosplate.com/product/vincenzos-plate-apron/\n\n🔄Kg to cups converter: http://www.convertunits.com/from/kilo+g/to/cup+[US]\n\nHOW TO MAKE SPAGHETTI CARBONARA\n\nINGREDIENTS:\n5L Water\nPinch rock salt\n300g/10 oz Spaghetti (or Spaghettoni/Rigatoni/Paccheri)\n150g/5.3 oz Guanciale \n200g (2 cups) Pecorino cheese\n4 eggs\nPepper\n\nUTENSILS:\nLarge pot for cooking pasta\nChopping Board\nKnife\nLarge fry pan\nMixing bowl\nFork\nLadle\nLong set of tongs\n\nMETHOD:\n1. Spaghetti carbonara takes just a short time to make so first up, boil the water to cook your pasta in a large pot.\n2. Cook the pasta according to the packet instructions when it comes to time, making sure the pasta is al dente.\n3. Cut the skin off the guanciale (making sure to leave the peppery/seasoned crust), then slice it into thin strips. \n4. Put the large fry pan on the stove at a low to medium heat. For the spaghetti carbonara recipe to be just right, add the guanciale into the pan, let it cook very slowly and it will create its own delicious oil.\n5. Let the guanciale simmer and crisp up very gently.\n6. Get your mixing bowl and add 4 eggs, then whisk them really well.\n7. Next, add the pecorino cheese to make this spaghetti carbonara recipe, and lots of pepper before mixing it together really well. This will create a scrumptious cream for you to add to your pasta.\n8. Once the pasta has boiled to your preferred taste, using a set of tongs, take out the pasta from the boiling water and add it straight to the pan, making sure small drops of the water mix into the pan too.\n9. Turn off the cook top, so the pasta and guanciale stop cooking.\n10. Next, using the ladle, get a full scoop of pasta water out of the pot and add it to the egg and cheese cream, then mix through well using a fork.\n\nRead more via\nhttps://www.vincenzosplate.com/spaghetti-carbonara-recipe/\n\n==========================================\n\nPlease Support My YouTube Channel via Patreon!  (Help me to create more content)\nhttps://www.patreon.com/vincenzosplate\n\n📖LIKE ME ON FACEBOOK https://www.facebook.com/vincenzosplate/\n\n📷FOLLOW ME ON INSTAGRAM @vincenzosplate   https://www.instagram.com/vincenzosplate/\n\n🌍Join my Small Group Private Italian Tour and discover the secret gems of Italy with me. Check out the itinerary and make sure you book asap (Only 10 spots available) http://www.vincenzosplate.com/italy-unexplored-itinerary/\n\nCheck out these PLAYLISTS:\n\n👪COOKING WITH MY FAMILY: https://www.youtube.com/playlist?list=PLJwrH1iB-tbepayGhQ6bwS202IgFm8uwV\n\n🍝PASTA RECIPES: https://www.youtube.com/watch?v=-8YhYnZNSVs&list=PLJwrH1iB-tbcJrYnFjobLWG6Ik8e8MZTZ\n\n🍕PIZZA RECIPES: https://www.youtube.com/playlist?list=PLJwrH1iB-tbcFaTg-8vUbJ8fAOYEWaXLL\n\n🍗MAIN COURSE RECIPES: https://www.youtube.com/playlist?list=PLJwrH1iB-tbf_mrFYE8bvpUHZ-tKPzdou\n\n🍰DESSERT RECIPES: https://www.youtube.com/playlist?list=PLJwrH1iB-tbfFsjUKcj3iEo6JmPxDIMQ6\n\n✔LIKE, SHARE and COMMENT on my videos please. It really means a lot to me.\n\n🎬 #VincenzosPlate is a YouTube channel with a focus on cooking, determined to teach the world, one #videorecipe at a time that you don’t need to be a professional #chef to impress friends, family and yourself with mouth-watering #ItalianFoodRecipes right out of your very own #kitchen whilst having a laugh (and a glass of vino!).\n\n#italianrecipes #italianfood #italiancuisine #bestcookingchannels #foodchannel",
        "age": "",
        "meta_url": {
          "profile_image": "https://yt3.ggpht.com/0DqTjDWS0itjaVcXiKyS0haSnJ95r0ywoR6JtCuUSNAbU6IkBh_ieQvq5uTNBJRSRfVk4Tj4_w=s800-c-k-c0x00ffffff-no-rj"
        },
        "thumbnail": {
          "original": "https://i.ytimg.com/vi/AvO8UPbIH30/maxresdefault.jpg"
        },
        "viewCount": 6763759,
        "likeCount": 126750,
        "channelTitle": "Vincenzo's Plate",
        "publishedAt": "2019-09-25T12:21:39Z",
        "duration": "PT14M56S"
      },
      {
        "title": "Can You Really Make Perfect Carbonara in 15 Minutes?",
        "url": "https://www.youtube.com/watch?v=lXEtC3Y9sqY",
        "description": "Try cooking the perfect Carbonara in just 15 minutes! In this video, you'll see the step-by-step process of cooking a delicious Italian dish from a POV (first-person perspective) that will make you feel like a real chef. We'll show you how to use simple ingredients and cook quickly and easily. Don't forget to put a like, leave a comment and subscribe to our channel so you don't miss new recipes for quick and delicious dishes!\n\n #Carbonara #ItalianCuisine #FastRecipes #POVCooking #POVCooking #Dinner Recipes #Pasta #DeliciousRecipes #CarbonaraRecipe #15Minutes #DenisInTheKitchen #Denis Prokopyev",
        "age": "",
        "meta_url": {
          "profile_image": "https://yt3.ggpht.com/Z9xKrcoKxbNMOjqpDQNOWPkJ90hU-G9ozMM6JKDkimXPKLn23jNVaEsjX-SDcoHxRKTaTz5mVQ=s800-c-k-c0x00ffffff-no-rj"
        },
        "thumbnail": {
          "original": "https://i.ytimg.com/vi/lXEtC3Y9sqY/maxresdefault.jpg"
        },
        "viewCount": 4402734,
        "likeCount": 75897,
        "channelTitle": "Denis Prokopyev",
        "publishedAt": "2024-09-12T19:11:58Z",
        "duration": "PT15M41S"
      }
    ]
  },
  {
    "id": "store-example-videos-search-3",
    "query": "how black holes work explained",
    "query_translation_key": "app_store_examples.videos.search.3",
    "provider": "Brave Search",
    "status": "finished",
    "results": [
      {
        "title": "Black Holes Explained – From Birth to Death",
        "url": "https://www.youtube.com/watch?v=e-P5IFTqB98",
        "description": "Black holes. Lets talk about them.\n\n\nOUR CHANNELS\n▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀\nGerman Channel: https://kgs.link/youtubeDE \nSpanish Channel: https://kgs.link/youtubeES \n\n\nHOW CAN YOU SUPPORT US?\n▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀\nThis is how we make our living and it would be a pleasure if you support us!\n\nGet Merch designed with ❤ from https://kgs.link/shop  \nJoin the Patreon Bird Army 🐧 https://kgs.link/patreon  \n\n\nDISCUSSIONS & SOCIAL MEDIA\n▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀\nReddit:            https://kgs.link/reddit\nInstagram:     https://kgs.link/instagram\nTwitter:           https://kgs.link/twitter\nFacebook:      https://kgs.link/facebook\nDiscord:          https://kgs.link/discord\nNewsletter:    https://kgs.link/newsletter\n\n\nOUR VOICE\n▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀\nThe Kurzgesagt voice is from \nSteve Taylor:  https://kgs.link/youtube-voice\n\n\nOUR MUSIC ♬♪\n▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀\n700+ minutes of Kurzgesagt Soundtracks by Epic Mountain:\n\nSpotify:            https://kgs.link/music-spotify\nSoundcloud:   https://kgs.link/music-soundcloud\nBandcamp:     https://kgs.link/music-bandcamp\nYoutube:          https://kgs.link/music-youtube\nFacebook:       https://kgs.link/music-facebook\n\nThe Soundtrack of this video:\n\nhttps://soundcloud.com/epicmountain/black-holes\nhttps://epicmountainmusic.bandcamp.com/track/black-holes\nhttp://epic-mountain.com\n\nHelp us caption & translate this video!\n\nhttp://www.youtube.com/timedtext_cs_panel?c=UCsXVk37bltHxD1rDPwtNM8Q&tab=2",
        "age": "",
        "meta_url": {
          "profile_image": "https://yt3.ggpht.com/ytc/AIdro_n1Ribd7LwdP_qKtqWL3ZDfIgv9M1d6g78VwpHGXVR2Ir4=s800-c-k-c0x00ffffff-no-rj"
        },
        "thumbnail": {
          "original": "https://i.ytimg.com/vi/e-P5IFTqB98/maxresdefault.jpg"
        },
        "viewCount": 27222993,
        "likeCount": 401137,
        "channelTitle": "Kurzgesagt – In a Nutshell",
        "publishedAt": "2015-12-15T16:33:55Z",
        "duration": "PT5M56S"
      },
      {
        "title": "Black Holes 101 | National Geographic",
        "url": "https://www.youtube.com/watch?v=kOEDG3j1bjs",
        "description": "At the center of our galaxy, a supermassive black hole churns. Learn about the types of black holes, how they form, and how scientists discovered these invisible, yet extraordinary objects in our universe.\n➡ Subscribe: https://on.natgeo.com/4p5A0D6\n\n#NationalGeographic #BlackHoles #Educational\n\nAbout National Geographic:\nNational Geographic is the world's premium destination for critically acclaimed storytelling around science and exploration. Discover amazing wildlife, ancient civilizations, hidden worlds, and the incredible wonders of our Earth. Through world-class scientists, photographers, journalists, and filmmakers, Nat Geo inspires fans of all ages to connect with, explore, and care about the world.\n\nGet More National Geographic:\nOfficial Site: https://nationalgeographic.com\nInstagram: https://instagram.com/natgeo \nFacebook: https://facebook.com/natgeo\nThreads: https://threads.com/@natgeo\nX: https://x.com/NatGeo\nLinkedIn: https://linkedin.com/company/national-geographic\nTikTok: https://tiktok.com/@natgeo\nReddit: https://reddit.com/user/nationalgeographic\n\nRead more at \"Black Holes 101\"\nhttps://on.natgeo.com/2Q7SykY\n\nBlack Holes 101 | National Geographic \nhttps://youtu.be/kOEDG3j1bjs\n\nNational Geographic\nhttps://www.youtube.com/natgeo",
        "age": "",
        "meta_url": {
          "profile_image": "https://yt3.ggpht.com/lSalOZV0QHCVcSJI8962l2HrEscpczQFXmyAoSI6stkw2pAyNJlhcK26P-npagYfWb27MzxmMw=s800-c-k-c0x00ffffff-no-rj"
        },
        "thumbnail": {
          "original": "https://i.ytimg.com/vi/kOEDG3j1bjs/maxresdefault.jpg"
        },
        "viewCount": 10943744,
        "likeCount": 96801,
        "channelTitle": "National Geographic",
        "publishedAt": "2018-09-20T20:00:01Z",
        "duration": "PT3M11S"
      },
      {
        "title": "How to Understand What Black Holes Look Like",
        "url": "https://www.youtube.com/watch?v=zUyH3XhpLTo",
        "description": "We have just seen the first image of a black hole, the supermassive black hole in the galaxy M87 with a mass 6.5 billion times that of our sun. But what is that image really showing us?\n\nThis is an awesome paper on the topic by J.P. Luminet:\nImage of a spherical black hole with thin accretion disk\nAstronomy and Astrophysics, vol. 75, no. 1-2, May 1979, p. 228-235\nhttps://ve42.co/luminet\n\nUsing my every day intuition I wondered: will we see the \"shadow\" of the black hole even if we're looking edge on at the accretion disk? The answer is yes because the black hole warps space-time, so even if we wouldn't normally be able to see the back of the accretion disk, we can in this case because its light is bent up and over the black hole. Similarly we can see light from the bottom of the back of the accretion disk because it's bent under the bottom of the black hole. Plus there are additional images from light that does a half turn around the black hole leading to the inner rings.\n\nWhat about the black hole \"shadow\" itself? Well initially I thought it can't be an image of the event horizon because it's so much bigger (2.6 times bigger). But if you trace back the rays, you find that for every point in the shadow, there is a corresponding ray that traces back to the event horizon. So in fact from our one observing location, we see all sides of the event horizon simultaneously! In fact infinitely many of these images, accounting for the virtually infinite number of times a photon can orbit the black hole before falling in. The edge of the shadow is due to the photon sphere - the radius at which light goes around in closed orbits. If a light ray coming in at an oblique angle just skims the photon sphere and then travels on to our telescopes, that is the closest 'impact parameter' possible, and it occurs at sqrt(27)/2*r_s\n\nHuge thanks to:\nProf. Geraint Lewis \nUniversity of Sydney https://ve42.co/gfl\nLike him, I'm hoping (predicting?) we'll see some moving images of black holes tomorrow\n\nProf. Rana Adhikari\nCaltech https://ve42.co/Rana\n\nRiccardo Antonelli - for excellent images of black holes, simulations and ray-tracing code, check out:\nhttps://ve42.co/rantonels\n\nThe Event Horizon Telescope Collaboration\nCheck out their resources and get your local link for the livestream here: https://ve42.co/EHT\n\nSpecial thanks to Patreon supporters:\nDonal Botkin, Michael Krugman, Ron Neal, Stan Presolski, Terrance Shepherd, Penward Rhyme\n\nFilming by Raquel Nuno\nAnimation by Maria Raykova",
        "age": "",
        "meta_url": {
          "profile_image": "https://yt3.ggpht.com/7vCbvtCqtjQ3YLgsJt7Y952MQV1sBvhllSCSxHP8_sVZdcPCBrITfhkN2RdyCuwPnsByq-1GoA=s800-c-k-c0x00ffffff-no-rj"
        },
        "thumbnail": {
          "original": "https://i.ytimg.com/vi/zUyH3XhpLTo/maxresdefault.jpg"
        },
        "viewCount": 10918243,
        "likeCount": 384528,
        "channelTitle": "Veritasium",
        "publishedAt": "2019-04-09T13:00:10Z",
        "duration": "PT9M19S"
      },
      {
        "title": "Why Black Hole Environments Are a Lot More Complicated Than We Thought",
        "url": "https://www.youtube.com/watch?v=qp2cqDkAU-0",
        "description": "Supercut of the Black Holes series. Learn about how black holes form, about their features, and how they warp the universe beyond our ability to comprehend. One things is for sure, the existence of black holes means we can't take our \"normal\" as a given.\n\nAstrum merch now available! \nApparel: https://astrum-shop.fourthwall.com/ \nMetal Posters: https://displate.com/promo/astrum?art=5f04759ac338b\n\nSUBSCRIBE for more videos about our other planets.\nSubscribe! http://goo.gl/WX4iMN\nFacebook! http://goo.gl/uaOlWW\nTwitter! http://goo.gl/VCfejs\nInstagram! https://www.instagram.com/astrumspace/\nTikTok! https://www.tiktok.com/@astrumspace\n\nAstrum Spanish: https://bit.ly/2KmkssR\nAstrum Portuguese: https://www.youtube.com/channel/UChn_-OwvV63mr1yeUGvH-BQ\n\nDonate! \nPatreon: http://goo.gl/GGA5xT\nEthereum Wallet: 0x5F8cf793962ae8Df4Cba017E7A6159a104744038\n\nBecome a Patron today and support my channel! Donate link above. I can't do it without you. Thanks to those who have supported so far!\n\n#blackhole #existentialcrisis #astrum \n\nrelativistic jets accretion disk photon ring event horizon",
        "age": "",
        "meta_url": {
          "profile_image": "https://yt3.ggpht.com/ytc/AIdro_nrZcjMi8ROqrLI5oJFbGoXg3zC4GCwxMBpouaNHGjZ5Wo=s800-c-k-c0x00ffffff-no-rj"
        },
        "thumbnail": {
          "original": "https://i.ytimg.com/vi/qp2cqDkAU-0/maxresdefault.jpg"
        },
        "viewCount": 4953077,
        "likeCount": 65984,
        "channelTitle": "Astrum",
        "publishedAt": "2022-10-04T15:44:34Z",
        "duration": "PT1H5M51S"
      }
    ]
  }
]

export default examples;
