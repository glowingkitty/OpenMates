/**
 * App-store examples for the web skill.
 *
 * Captured from real Brave Search responses with everyday non-technical queries that reflect how most people use a search skill.
 */

export interface WebSearchStoreExample {
  id: string;
  query: string;
  query_translation_key?: string;
  provider?: string;
  status: 'finished';
  results: Array<Record<string, unknown>>;
  url?: string;
}

const examples: WebSearchStoreExample[] = [
  {
    "id": "store-example-web-search-1",
    "query": "Quick healthy dinner recipes under 30 minutes",
    "query_translation_key": "settings.app_store_examples.web.search.1",
    "provider": "Brave Search",
    "status": "finished",
    "results": [
      {
        "title": "Healthy 30-Minute Dinners & Recipes - Jar Of Lemons",
        "url": "https://www.jaroflemons.com/category/food/easy-everyday/30-minute-dinners/",
        "description": "Need dinner in a pinch? These 30-minute dinners are healthy, delicious, and easy to make! No complicated ingredients or processes here. Just quick, easy meals that everyone will love! ... This Chicken Shawarma Pizza recipe combines several of my favorite foods to create one super fun meal!",
        "page_age": "",
        "profile": {
          "name": "Jar Of Lemons"
        },
        "meta_url": {
          "favicon": "https://imgs.search.brave.com/p6Sja4u_PfJL2IOEBpjyUpT5LxZOsUzEt3JJ2NO6b_I/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvNjdiZmRkZmY1/NzE5NmEzZjdkMjQ0/MTI5OGFmNWI1NjVj/MGU5NmFlNjI1M2Zl/YTVmNWM3MDBjOWY0/MjI2MzE5Mi93d3cu/amFyb2ZsZW1vbnMu/Y29tLw"
        },
        "thumbnail": {
          "src": "https://imgs.search.brave.com/YxXtb9YKpEA9Jna0lIkDK3cJ-S_CyHNoJYMJt_Uf02M/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly93d3cu/amFyb2ZsZW1vbnMu/Y29tL3dwLWNvbnRl/bnQvdXBsb2Fkcy8y/MDI2LzAzL01lZGl0/ZXJyYW5lYW4tQ2hp/Y2tlbi1TaGF3YXJt/YS1QaXp6YXMtMy5q/cGc",
          "original": "https://www.jaroflemons.com/wp-content/uploads/2026/03/Mediterranean-Chicken-Shawarma-Pizzas-3.jpg"
        },
        "extra_snippets": [
          "These healthy 30-minute dinners are delicious and easy to make! Perfect for dinner, lunch, or any time of day. These popular meals are so good!",
          "My favorite way to use up leftovers, these pizzas are perfect for a quick and easy dinner when I really don’t feel like cooking, and my littles always have fun getting to add their own toppings. Plus, they’re ready to eat in less than 20 minutes and have 30 grams of protein! Read Post View Recipe Index"
        ]
      },
      {
        "title": "51 Low-Lift 30-Minute Meals for Nights When You Just Can’t | Epicurious",
        "url": "https://www.epicurious.com/recipes-menus/30-minute-meals-gallery",
        "description": "Enter these quick recipes: easy ... much cook time. There are pastas, of course, but also 10-minute skillet sautés, shockingly quick vegetarian chili, and the speediest pork chops and chicken....",
        "page_age": "January 14, 2022",
        "profile": {
          "name": "Epicurious"
        },
        "meta_url": {
          "favicon": "https://imgs.search.brave.com/xttGEY12UJulZK4-4HtlXbETEAWuj2Y7OSUxWy4NbsE/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvYzI4NTNlMzlk/OTM5ZjZhN2M3OWIw/MzIzZGJlYjNhYzEz/OTE2ZTA3Y2E5YTU1/NmY1N2MzYmJiNGVm/Mjk0YzZiYy93d3cu/ZXBpY3VyaW91cy5j/b20v"
        },
        "thumbnail": {
          "src": "https://imgs.search.brave.com/eWBykzutWUhMd7mbuRwUzWldQkL-B6bT0EEHrHgFN9o/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly9hc3Nl/dHMuZXBpY3VyaW91/cy5jb20vcGhvdG9z/LzYwOWFjNWZhZjQ3/OWUzZDRmNmM1Mjgx/YS8xNjo5L3dfNTI3/NyxoXzI5NjgsY19s/aW1pdC9TYWxtb25D/cm9xdWV0dGVzX0hF/Uk9fMDUwNjIxXzE0/NjUzLmpwZw",
          "original": "https://assets.epicurious.com/photos/609ac5faf479e3d4f6c5281a/16:9/w_5277,h_2968,c_limit/SalmonCroquettes_HERO_050621_14653.jpg"
        },
        "extra_snippets": [
          "Delicious ways to get dinner on the table, even when it feels impossible. Find 30-minute meals including chicken, pasta, pork chops, quick chili, and more.",
          "Sometimes, on a work-from-home day, I’m lucky enough to be able to put together a slow braise or soup that cooks, hands-off, while I do something else, but many, many nights I find myself with precisely half an hour to get dinner on the table and precisely zero housemates interested in eating scrambled eggs. Enter these quick recipes: easy weeknight options that are full of flavor but don’t require much cook time. There are pastas, of course, but also 10-minute skillet sautés, shockingly quick vegetarian chili, and the speediest pork chops and chicken.",
          "And when all else fails, there are pancakes, with a roasted-fruit sauce that makes breakfast for dinner feel like more than a backup plan. ... I often lean on pasta when I'm crunched for time and looking for 30-minute meals, but seafood is absolutely doable in half an hour or less. You can make salmon even more quick-cooking by cubing the fish—roasted at high heat, it gets crispy exteriors before it's overcooked inside. The creamy marinade in this recipe brings flavor, while also keeping the salmon moist.",
          "Bake salmon fillets next to tender spring asparagus on one sheet pan for an easy fish dinner that comes together in just 20 minutes. ... In this riff on dubu jorim, a popular Korean side dish, thick slices of pan-fried tofu quickly braise in a sweet-and-spicy sauce. This recipe is a favorite in my household—and it will be in yours, too."
        ]
      },
      {
        "title": "30 Minute Meals - Quick & Healthy Dinner Ideas!",
        "url": "https://www.joyfulhealthyeats.com/recipes/easy-healthy-dinners/30-minute-meals/",
        "description": "Use this collection of 30 minute meals to get a healthy dinner on the table for your family in minutes! If you’re looking for a simple dinner that’s a guaranteed hit with the kiddos, try something like these crispy Air Fryer Chicken Tenders! They’re perfectly juicy and packed with flavor. Or, make something like these Grilled Chicken Breasts that go with literally everything. Rice, roasted potatoes, veggies, salad, you name it. They’re quick, easy, adaptable, and so tasty!",
        "page_age": "",
        "profile": {
          "name": "Joyful Healthy Eats"
        },
        "meta_url": {
          "favicon": "https://imgs.search.brave.com/U1EoZOtdQ6saQXmar7UOswnnVNWEndACk-juHv8CKeE/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvNGExY2FiZTMx/NTNiNmQ4Y2NkMmJk/ZmRkMDE0MjhmMmVm/Y2JjMTk1ZDVhZTM4/NDJmNTQ0NDIzNjUz/ZmI4MDRhZi93d3cu/am95ZnVsaGVhbHRo/eWVhdHMuY29tLw"
        },
        "thumbnail": {
          "src": "https://imgs.search.brave.com/bj5cw5GwAk_RWcmo6FWfjm2jRwXLvaGHpARbqw9bUf8/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly93d3cu/am95ZnVsaGVhbHRo/eWVhdHMuY29tL3dw/LWNvbnRlbnQvdXBs/b2Fkcy8yMDE4LzA2/L1NlYXJlZC1TY2Fs/bG9wcy13aXRoLUNv/cm4tUmVsaXNoLXdl/Yi0xLmpwZw",
          "original": "https://www.joyfulhealthyeats.com/wp-content/uploads/2018/06/Seared-Scallops-with-Corn-Relish-web-1.jpg"
        },
        "extra_snippets": [
          "I should also note that you’ll find a number of quick side dishes, breakfast recipes, and more here, as well. Just because these dinners come together in a snap doesn’t mean that they aren’t super delicious and packed with fresh ingredients! These are some of my favorite healthy dinners that I think you’ll love just as much as I do. ... You’ve got a lot of choices here, so if you’re not sure where to start, try one of these popular 30 minute meals!",
          "If time is limited, don't spend it slaving at the stove. Use this collection of 30 minute meals to get a healthy dinner on the table in minutes!",
          "Use this collection of 30 minute meals to get a healthy dinner on the table for your family in minutes! If you’re looking for a simple dinner that’s a guaranteed hit with the kiddos, try something like these crispy Air Fryer Chicken Tenders! They’re perfectly juicy and packed with flavor. Or, make something like these Grilled Chicken Breasts that go with literally everything. Rice, roasted potatoes, veggies, salad, you name it. They’re quick, easy, adaptable, and so tasty!",
          "Home » Recipes » Easy Healthy Dinners » 30 Minute Meals"
        ]
      },
      {
        "title": "30 Healthy Recipes In 30 Minutes Or Less - Downshiftology",
        "url": "https://downshiftology.com/30-healthy-recipes-30-minutes-or-less/",
        "description": "Chicken Stir Fry: This is reminiscent of your favorite Chinese take-out, but with a healthier (and tastier) twist. It only requires 30 minutes on the stove and will fill up the entire family.",
        "page_age": "January 27, 2026",
        "profile": {
          "name": "Downshiftology"
        },
        "meta_url": {
          "favicon": "https://imgs.search.brave.com/HyaDqknjl-FS-jujJERxP9zLo6pIQV_RrM5ToUj6rTw/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvN2I3OTk2NDky/NzYxMGVlMDJjMDA1/NGViMDViMTYwZDZk/ODdkYTQxZDQzNGQ3/MTVhMjk1M2IzMTI0/NDM2ZWMyMi9kb3du/c2hpZnRvbG9neS5j/b20v"
        },
        "thumbnail": {
          "src": "https://imgs.search.brave.com/Y8WZ1fxMWGq64BOLbWxrAF_tO25YG6_H9opbdlksU6c/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly9pMi53/cC5jb20vd3d3LmRv/d25zaGlmdG9sb2d5/LmNvbS93cC1jb250/ZW50L3VwbG9hZHMv/MjAyMi8wMy9IZWFs/dGh5LVJlY2lwZXMu/anBn",
          "original": "https://i2.wp.com/www.downshiftology.com/wp-content/uploads/2022/03/Healthy-Recipes.jpg"
        },
        "extra_snippets": [
          "Healthy recipes in 30 minute or less? Who doesn’t love that? Choose from a variety of seafood favorites, chicken dinners every which way, hearty vegetarian meals, and the best throw-together recipes when you need something extra zippy (and fast). Time… oh, it’s something we all need more of, isn’t it? From notoriously busy weekdays to event filled weekends, getting in a quick (yet healthy) meal can often feel time consuming.",
          "For more dinner inspiration check out my best easy dinner ideas, best meal prep recipes, and best vegetarian recipes! There’s plenty of options to choose from when you’re on a time crunch. If you try any of these healthy recipes made in 30 minutes or under, I’d love to hear which ones are your favorite in a comment below!",
          "These healthy, 30-minute recipes are the perfect mix of seafood favorites, chicken dinners, hearty vegetarian meals, and so much more!",
          "And if you do a little prep work ahead of time – these six awesome chicken marinades will come in handy for quick dinners with seriously good flavors. Coconut Curry Chicken: Curry spices always elevate any meal, especially when paired with coconut milk and herbs. And if you’ve got leftover spices, whip up a curried egg salad! Chicken Stir Fry: This is reminiscent of your favorite Chinese take-out, but with a healthier (and tastier) twist. It only requires 30 minutes on the stove and will fill up the entire family."
        ]
      }
    ]
  },
  {
    "id": "store-example-web-search-2",
    "query": "Best family-friendly beaches in southern Europe",
    "query_translation_key": "settings.app_store_examples.web.search.2",
    "provider": "Brave Search",
    "status": "finished",
    "results": [
      {
        "title": "Best Beaches in Europe With Kids - We Go With Kids!",
        "url": "https://wegowithkids.com/europe-with-kids-fun-family-beaches/",
        "description": "Situated on the Mediterranean Sea with calm little waves and stunning clear water, it is just a little paradise to spend all day in the sun and swim, snorkel and play. We have visited many beaches together, and even though it is hard to pick one we think that Paleokastritsa beach in Corfu is the ...",
        "page_age": "April 5, 2019",
        "profile": {
          "name": "We Go With Kids!"
        },
        "meta_url": {
          "favicon": "https://imgs.search.brave.com/uKMvtqju7Q4TzNUY0tjuQqVMMJf4x1U1nFeQeH1Bufg/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvMTZjNDcwMGIy/NjhjNWYzMTE2MTBh/ODU2NTY2YmE1MDk2/YjlkOGU4MWZkNDBj/OTNhNzZhYzczODQ5/YzE0NGMzNS93ZWdv/d2l0aGtpZHMuY29t/Lw"
        },
        "extra_snippets": [
          "Europe's capital cities may attract more attention than its beaches, but sun and sand makes for an ideal vacation with kids. Travelers in search of picturesque beaches often focus more on the Caribbean or South Pacific. However, it is possible to combine both beach and city visits into the same European vacation.",
          "There is a boardwalk from the square next to the car park which leads visitors to a beautiful sandy beach. During summer, there are sunbeds and parasols for rent. What makes it family-friendly is that it has toilets on the boardwalk, next to a great restaurant.",
          "The Greek Island of Corfu has so many amazing beaches for families. Situated on the Mediterranean Sea with calm little waves and stunning clear water, it is just a little paradise to spend all day in the sun and swim, snorkel and play. We have visited many beaches together, and even though it is hard to pick one we think that Paleokastritsa beach in Corfu is the best child friendly beach around.",
          "Travelers in search of picturesque beaches often focus more on the Caribbean or South Pacific. However, it is possible to combine both beach and city visits into the same European vacation. Most importantly, these are kid-tested and recommended by other traveling families."
        ]
      },
      {
        "title": "11 Best Beaches in Europe for Families That Are Kid-Approved",
        "url": "https://www.beach.com/family/best-beaches-in-europe-for-families/",
        "description": "Tropea immediately takes your breath away. Set on Costa degli Dei in Italia’s southernmost Calabria region, this town is also a very family-friendly destination with some of the most gorgeous beaches in Europe. The main stretch is located right underneath the Old Town next to the mighty rocks.",
        "page_age": "August 11, 2025",
        "profile": {
          "name": "Beach.com"
        },
        "meta_url": {
          "favicon": "https://imgs.search.brave.com/UAW9RcWWAfKoKCMSVt3X-oMI0e3C9Jh9MNrZmjv-pao/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvOTFkNjIxNTc3/MGFmMzE4ZTVkNzhm/ODFlNzcyYzc0NjVi/YzVlODViZTFlM2Nk/ZDcxYmYwNjUwNjAy/YTgzN2E2NS93d3cu/YmVhY2guY29tLw"
        },
        "thumbnail": {
          "src": "https://imgs.search.brave.com/zTOfNsB6j28zR-pu5w-rnO2-1UYog7AG8UwGRKqfPXk/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly93d3cu/YmVhY2guY29tL3dw/LWNvbnRlbnQvdXBs/b2Fkcy8yMDI1LzAy/L2RyZWFtc3RpbWVf/MzU1MzQ5NDEzLXNj/YWxlZC5qcGc",
          "original": "https://www.beach.com/wp-content/uploads/2025/02/dreamstime_355349413-scaled.jpg"
        },
        "extra_snippets": [
          "This list is a collection of the best beaches in Europe for families. We considered factors such as easy water access, available facilities, activities, cleanliness and family-friendly infrastructure to give you the top options for the 2025 vacation season. Also, it includes my personal experience of spending summers on southern Europe’s beaches.",
          "Tropea immediately takes your breath away. Set on Costa degli Dei in Italia’s southernmost Calabria region, this town is also a very family-friendly destination with some of the most gorgeous beaches in Europe. The main stretch is located right underneath the Old Town next to the mighty rocks.",
          "Discover the best beaches in Europe for families, featuring shallow waters, soft sands and great facilities for a stress-free vacation.",
          "So here’s where to get sun and fun with kids in Europe this year. ... Possibly Sardinia’s most stunning beach, Porto Giunco is also a top pick for families. Located on the island’s southern coast, it’s a gorgeous 2-mile-long stretch of finest white sands with clear sea."
        ]
      },
      {
        "title": "Top 9 Best Beaches in Europe for Families - Vacation",
        "url": "https://insidervillas.com/best-beach-vacation-with-kids-in-europe/",
        "description": "However, isn’t just about luxury; it also offers fantastic family-friendly destinations with calm waters, charming old towns, and kid-friendly attractions. Plage de la Garoupe (Antibes): A lesser-known beach with shallow waters and a relaxed vibe. Marineland (Antibes): One of Europe’s best marine parks, featuring dolphin and sea lion shows.",
        "page_age": "January 22, 2026",
        "profile": {
          "name": "Insider Villas"
        },
        "meta_url": {
          "favicon": "https://imgs.search.brave.com/j07BN7U-12nTgEIyJmryUyYFqvPHL65gHchBEnH4w1U/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvYTUzNGQwMDFl/NDY3NGVlOGRjNzFl/MWFiZTkxZGU4MjFl/ZDBiMTBhZmFlNGY0/NmFkMjI0NWM0ZDEw/YWUzM2MzNi9pbnNp/ZGVydmlsbGFzLmNv/bS8"
        },
        "thumbnail": {
          "src": "https://imgs.search.brave.com/rEUrMqJFU6_0RuhF8nSL9thtbllzsVyjpZRJA3-dt9k/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly9pbnNp/ZGVydmlsbGFzLmNv/bS93cC1jb250ZW50/L3VwbG9hZHMvMjAy/Mi8wOS9MYS1DaWdh/bGUtMjAyMi0xOS4x/LmpwZw",
          "original": "https://insidervillas.com/wp-content/uploads/2022/09/La-Cigale-2022-19.1.jpg"
        },
        "extra_snippets": [
          "However, isn’t just about luxury; it also offers fantastic family-friendly destinations with calm waters, charming old towns, and kid-friendly attractions. Plage de la Garoupe (Antibes): A lesser-known beach with shallow waters and a relaxed vibe. Marineland (Antibes): One of Europe’s best marine parks, featuring dolphin and sea lion shows.",
          "You will create lasting memories in beautiful places that have family-friendly options. So, pack your bags, enjoy the sun, and make unforgettable moments on the best beaches in Europe for a great family vacation.",
          "Europe has many safe beaches that are great for kids. These spots have calm blue waters and soft white sand, perfect for lots of fun. You should look for beaches that have shallow areas, lifeguards present, and gentle waves. This makes them a good choice for families with young children. Many websites focus on family-friendly villas.",
          "The Algarve is found on the southern coast of Portugal. It is famous for its beautiful beaches and tall cliffs, and it is great for families."
        ]
      },
      {
        "title": "r/travel on Reddit: Family friendly beach destinations in Europe in September and early October",
        "url": "https://www.reddit.com/r/travel/comments/1atnrgs/family_friendly_beach_destinations_in_europe_in/",
        "description": "In Greece you could look at Rhodes, Syros, Naxos, Corfu, Samos for islands, or on the mainland, the area around Kalamata has a bunch of nice places to visit: Pylos, Methoni, Koroni, ancient Messene, Kardamyli, Stoupa, and it isn't that far to ...",
        "page_age": "February 18, 2024",
        "profile": {
          "name": "Reddit"
        },
        "meta_url": {
          "favicon": "https://imgs.search.brave.com/U-eHNCapRHVNWWCVPPMTIvOofZULh0_A_FQKe8xTE4I/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvN2ZiNTU0M2Nj/MTFhZjRiYWViZDlk/MjJiMjBjMzFjMDRk/Y2IzYWI0MGI0MjVk/OGY5NzQzOGQ5NzQ5/NWJhMWI0NC93d3cu/cmVkZGl0LmNvbS8"
        },
        "thumbnail": {
          "src": "https://imgs.search.brave.com/A5H_aQiEBuUODR0lNeU8iDfhrWUvO8oEmRGE_mcS_gM/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly93d3cu/cmVkZGl0c3RhdGlj/LmNvbS9pY29uLnBu/Zw",
          "original": "https://www.redditstatic.com/icon.png"
        },
        "extra_snippets": [
          "Any family-friendly destination in Europe that surprised you? r/familytravel • · upvotes · · comments · European countries ranked by safety · r/Maps • · comments · 10 of the best beaches in Europe for families. r/Finland • · upvotes · · comments · Ideas for where to holiday with our 7 month baby in June · r/travel • · comments · Suggestions for a 1-week trip with nice beaches in Southern Europe in September?",
          "Ideal location would be a city or town with a nice family friendly beach walking distance from the touristy/historic centre. Ideally, there are other nearby day trip options in order to fill up 1-2 weeks.",
          "In Greece you could look at Rhodes, Syros, Naxos, Corfu, Samos for islands, or on the mainland, the area around Kalamata has a bunch of nice places to visit: Pylos, Methoni, Koroni, ancient Messene, Kardamyli, Stoupa, and it isn't that far to do longish day trips to Olympia and Mystras. Koroni has a nice beach (Zaga) and is walkable, but lots of stairs! Methoni has a shallow beach. Kalamata has a beach too but it's less toddler friendly, Maybe check out the beaches at the towns just E of Kalamata.",
          "Seeking beach locations in Europe that will still be warm (and not windy) in late September / October, so that we can swim in the sea."
        ]
      }
    ]
  },
  {
    "id": "store-example-web-search-3",
    "query": "Natural ways to improve your sleep",
    "query_translation_key": "settings.app_store_examples.web.search.3",
    "provider": "Brave Search",
    "status": "finished",
    "results": [
      {
        "title": "Natural Sleep Aids: Home Remedies to Help You Sleep | Johns Hopkins Medicine",
        "url": "https://www.hopkinsmedicine.org/health/wellness-and-prevention/natural-sleep-aids-home-remedies-to-help-you-sleep",
        "description": "Though there isn’t much scientific proof that any of these nighttime drinks work to improve your slumber, there’s no harm in trying them, Gamaldo says. She recommends them to patients who want treatment without side effects or drug interactions. “Warm milk has long been believed to be associated with chemicals that simulate the effects of tryptophan on the brain. This is a chemical building block for the substance serotonin, which is involved in the sleep-wake transition,” Gamaldo says.",
        "page_age": "February 23, 2026",
        "profile": {
          "name": "Johns Hopkins Medicine"
        },
        "meta_url": {
          "favicon": "https://imgs.search.brave.com/gqzPsxLrZGxopKhm8NRd8H2x2MDbfKkhdDvgQ85_20A/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvNjcxYjExNTBj/MDRmYmEzNzAzZmI2/ZjdlNjRlMzFiNDU4/ZDQ2MWE3ODE1MTAy/NzI0YzQzYmIzMDQz/YzJmZDRhYi93d3cu/aG9wa2luc21lZGlj/aW5lLm9yZy8"
        },
        "thumbnail": {
          "src": "https://imgs.search.brave.com/OoLis6ZJVIvjEUyRgLir-C-eJ_B09HHz_INDhfHHkaA/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly93d3cu/aG9wa2luc21lZGlj/aW5lLm9yZy8tL21l/ZGlhL2ltYWdlcy9o/ZWFsdGgvXy1pbWFn/ZXMtdG8tYmUtZmls/ZWQvaXN0b2NrODI3/MjE1NzI0LmpwZw",
          "original": "https://www.hopkinsmedicine.org/-/media/images/health/_-images-to-be-filed/istock827215724.jpg"
        },
        "extra_snippets": [
          "Happily, there are easy, natural fixes that can improve your sleep, says Charlene Gamaldo, M.D. , medical director of Johns Hopkins Center for Sleep at Howard County General Hospital. “It’s not always necessary to get a prescription for a sleep aid,” she says. “There are natural ways to make adjustments to your sleeping habits.”",
          "Are you having trouble drifting into a peaceful, nourishing slumber? A Johns Hopkins expert says there are easy, natural fixes that can improve your sleep.",
          "Though there isn’t much scientific proof that any of these nighttime drinks work to improve your slumber, there’s no harm in trying them, Gamaldo says. She recommends them to patients who want treatment without side effects or drug interactions. “Warm milk has long been believed to be associated with chemicals that simulate the effects of tryptophan on the brain. This is a chemical building block for the substance serotonin, which is involved in the sleep-wake transition,” Gamaldo says.",
          "“Melatonin is a hormone that is naturally released in the brain four hours before we feel a sense of sleepiness,” Gamaldo says. It’s triggered by the body’s response to reduced light exposure, which should naturally happen at night. These days, though, lights abound after it’s dark outside—whether it’s from your phone, laptop or TV."
        ]
      },
      {
        "title": "5 Natural Sleep Aids to Help You Get a Better Night’s Sleep | INTEGRIS Health",
        "url": "https://integrishealth.org/resources/on-your-health/2023/august/5-natural-sleep-aids",
        "description": "Lavender, with its calming and ... and improve sleep. This fragrant herb can be incorporated into your nighttime routine in various ways. Try using lavender essential oil in a diffuser or adding a few drops to your bathwater. You can also place a sachet of dried lavender flowers near your pillow to enjoy its calming scent as you drift off to sleep. Known for its gentle sedative properties, chamomile tea has long been used as a natural remedy for ...",
        "page_age": "",
        "profile": {
          "name": "INTEGRIS Health"
        },
        "meta_url": {
          "favicon": "https://imgs.search.brave.com/rvS_gxAi2hpGxRqRmOQ8kmKk8WHfXOPXY3CuFnVEmIs/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvMGEwMDY3OTYz/ZGQ5MTk3ZTFiNTMy/NzY5MjZmMjEwZDMx/M2U4NGZlYTg5MGJk/MTFiZmU1MjEwODI4/MTU1NTNlOS9pbnRl/Z3Jpc2hlYWx0aC5v/cmcv"
        },
        "thumbnail": {
          "src": "https://imgs.search.brave.com/rXTLmwHqMhoB8mbgOYxm0EMcYWxqeGXisyBomiUtI50/rs:fit:200:200:1:0/g:ce/aHR0cDovL2ludGVn/cmlzaGVhbHRoLm9y/Zy9yZXNvdXJjZXMv/b24teW91ci1oZWFs/dGgvLS9tZWRpYS9i/bG9nLzIwMjMvb3lo/X3NsZWVwLWFpZGVz/LmpwZz9yZXZpc2lv/bj1lOGY5YTNjNS0x/OWE2LTQwNzUtYTU0/MC1hMDQyYzY0NDBj/OWM",
          "original": "http://integrishealth.org/resources/on-your-health/-/media/blog/2023/oyh_sleep-aides.jpg?revision=e8f9a3c5-19a6-4075-a540-a042c6440c9c"
        },
        "extra_snippets": [
          "Lavender, with its calming and soothing properties, has been used for centuries to promote relaxation and improve sleep. This fragrant herb can be incorporated into your nighttime routine in various ways. Try using lavender essential oil in a diffuser or adding a few drops to your bathwater. You can also place a sachet of dried lavender flowers near your pillow to enjoy its calming scent as you drift off to sleep. Known for its gentle sedative properties, chamomile tea has long been used as a natural remedy for promoting sleep.",
          "In today's fast-paced world, getting a restful night's sleep can sometimes feel like an elusive dream. Tossing and turning, staring at the ceiling and feeling exhausted the next day are all too common for many individuals. In this blog, we explore five natural sleep aids that can help you achieve a better quality of sleep.",
          "Sipping on a warm cup of chamomile tea before bedtime can help relax your mind and body, preparing you for a peaceful slumber. This herbal tea is caffeine-free and contains compounds that may have a calming effect on the nervous system, making it an ideal choice for those seeking a natural sleep aid.",
          "Additionally, establish a consistent sleep routine by going to bed and waking up at the same time each day, even on weekends. This regularity helps regulate your body's internal clock, promoting a more restful sleep. When it comes to achieving a better night's sleep, natural sleep aids can offer a gentle and effective alternative to medication."
        ]
      },
      {
        "title": "Sleep tips: 6 steps to better sleep - Mayo Clinic",
        "url": "https://www.mayoclinic.org/healthy-lifestyle/adult-health/in-depth/sleep/art-20048379",
        "description": "If you don't fall asleep within about 20 minutes of going to bed, leave your bedroom and do something relaxing. Read or listen to soothing music. Go back to bed when you're tired.",
        "page_age": "",
        "profile": {
          "name": "Mayo Clinic"
        },
        "meta_url": {
          "favicon": "https://imgs.search.brave.com/F1QZCikCU1Xq3h2jnFO_jszJNtkzLyankDCOWtGJmSQ/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvMGRiNzRkYTUy/ODQ5Y2IyY2EyNzU1/NjU1NWQ5NTZmNzY2/NjMxMGQyMzNjMjlm/NTc4NDk4Njg0M2Ix/M2I5ZGMzNC93d3cu/bWF5b2NsaW5pYy5v/cmcv"
        },
        "thumbnail": {
          "src": "https://imgs.search.brave.com/T_iBJF3z5itETD3mMQCjMMIYgld9v0daw24cO2_WkPk/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly93d3cu/bWF5b2NsaW5pYy5v/cmcvLS9tZWRpYS9X/ZWIvR0JTL1NoYXJl/ZC9JbWFnZXMvU29j/aWFsTWVkaWEtTWV0/YWRhdGEvTUNfVHdp/dHRlckNhcmRfMTIw/eDEyMC5qcGc",
          "original": "https://www.mayoclinic.org/-/media/Web/GBS/Shared/Images/SocialMedia-Metadata/MC_TwitterCard_120x120.jpg"
        },
        "extra_snippets": [
          "Many factors can interfere with a good night's sleep — from work stress and family responsibilities to illnesses. It's no wonder that quality sleep is sometimes elusive. You might not be able to control the factors that interfere with your sleep. However, you can adopt habits that encourage better sleep.",
          "The recommended amount of sleep for a healthy adult is at least seven hours. Most people don't need more than eight hours in bed to be well rested. Go to bed and get up at the same time every day, including weekends. Being consistent reinforces your body's sleep-wake cycle.",
          "If you don't fall asleep within about 20 minutes of going to bed, leave your bedroom and do something relaxing. Read or listen to soothing music. Go back to bed when you're tired. Repeat as needed, but continue to maintain your sleep schedule and wake-up time.",
          "Nicotine, caffeine and alcohol deserve caution, too. The stimulating effects of nicotine and caffeine take hours to wear off and can interfere with sleep. And even though alcohol might make you feel sleepy at first, it can disrupt sleep later in the night. Keep your room cool, dark and quiet."
        ]
      },
      {
        "title": "8 secrets to a good night's sleep - Harvard Health",
        "url": "https://www.health.harvard.edu/newsletter_article/8-secrets-to-a-good-nights-sleep",
        "description": "Going for a brisk daily walk won't just trim you down, it will also keep you up less often at night. Exercise boosts the effect of natural sleep hormones such as melatonin. Just watch the timing of your workouts.",
        "page_age": "November 20, 2023",
        "profile": {
          "name": "Harvard Health"
        },
        "meta_url": {
          "favicon": "https://imgs.search.brave.com/j0qbJL5nB_02qDDpu2mPR4DDnOvr0qAGrZyBmzE77KM/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvZjJjN2FiMzU1/MDI3ODgxMGQwNGQ5/OTJiZTU4YjBjM2Mz/ODE2NTA3ZGU0Y2Zi/M2UwMDMxNzUwY2Rk/YzgyZmI3OC93d3cu/aGVhbHRoLmhhcnZh/cmQuZWR1Lw"
        },
        "thumbnail": {
          "src": "https://imgs.search.brave.com/afVkWY2pPCtp9ka9mSL6rENkpZ662Jm2P6L9kyaLQwc/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly9kb21m/NW9pbzZxcmNyLmNs/b3VkZnJvbnQubmV0/L21lZGlhbGlicmFy/eS8xMTc2OC9jb252/ZXJzaW9ucy8xZWFi/MmNmNi01MDRmLTQy/NzMtYjI0Zi0wMGMz/MGFkNjI3YmQtdGh1/bWIuanBn",
          "original": "https://domf5oio6qrcr.cloudfront.net/medialibrary/11768/conversions/1eab2cf6-504f-4273-b24f-00c30ad627bd-thumb.jpg"
        },
        "extra_snippets": [
          "Going for a brisk daily walk won't just trim you down, it will also keep you up less often at night. Exercise boosts the effect of natural sleep hormones such as melatonin. Just watch the timing of your workouts. Exercising too close to bedtime can be stimulating.",
          "Morning workouts that expose you to bright daylight will help the natural circadian rhythm. Don't use your bed as an office for answering phone calls, texting, and responding to emails. Also, avoid watching late-night TV there. The bed needs to be a stimulus for sleeping, not for wakefulness.",
          "Restless nights and weary mornings can become more frequent as we get older and our sleep patterns change. Later in life there tends to be a decrease in the number of hours slept. There are also some changes in the way the body regulates circadian rhythms. This internal clock helps your body respond to changes in light and dark.",
          "Don’t miss out on your 25% off promo code and BONUS GIFT worth $29.95. Sign up to get tips for living a healthy lifestyle, with ways to lessen digestion problems…keep inflammation under control…learn simple exercises to improve your balance…understand your options for cataract treatment…all delivered to your email box FREE."
        ]
      }
    ]
  }
]

export default examples;
