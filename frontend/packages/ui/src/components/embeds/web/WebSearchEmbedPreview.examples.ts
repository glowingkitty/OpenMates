/**
 * App-store examples for the web search skill.
 *
 * Captured from real Brave Search responses via run_app_skill_request.py,
 * trimmed to 4 results per query. Used by SkillDetails.svelte to render
 * curated embed previews in the app store.
 *
 * To regenerate: run the web/search skill via backend/scripts/run_app_skill_request.py
 * with representative queries, then update this file.
 */

export interface WebSearchStoreExample {
  id: string;
  query: string;
  query_translation_key?: string;
  provider: string;
  status: 'finished';
  results: Array<Record<string, unknown>>;
}

const examples: WebSearchStoreExample[] = [
  {
    "id": "store-example-web-search-1",
    "query": "how to learn rust programming as a beginner",
    "query_translation_key": "settings.app_store_examples.web.search.1",
    "provider": "Brave Search",
    "status": "finished",
    "results": [
      {
        "title": "Learn Rust - Rust Programming Language",
        "url": "https://rust-lang.org/learn/",
        "description": "Affectionately nicknamed “the book,” The Rust Programming Language will give you an overview of the language from first principles. You’ll build a few projects along the way, and by the end, you’ll have a solid grasp of the language. Read the Book! If reading multiple hundreds of pages about a language isn’t your style, then Rust By Example has you covered. While the book talks about code with a lot of words, RBE shows off a bunch of code, and keeps the talking to a minimum.",
        "page_age": "",
        "profile": {
          "name": "Rust Programming Language"
        },
        "meta_url": {
          "favicon": "https://imgs.search.brave.com/KM3UVnh_2VxQjDofcZZ7qQzMlQVdYlUJC5n4bboPPGU/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvN2MzNTM1MGEx/ZTA0YTg3Y2U4NjA0/MTc1N2ViYjlkZDg5/OGY3NGQzMTliZGM2/Nzc1ZWMwMDlkNjhl/NTg1OGVlMC9ydXN0/LWxhbmcub3JnLw"
        },
        "thumbnail": {
          "src": "https://imgs.search.brave.com/Po8v03a3zxl8BkJx3U8wTIz7XG9Oesw6OljvjcEYlac/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly93d3cu/cnVzdC1sYW5nLm9y/Zy9zdGF0aWMvaW1h/Z2VzL3J1c3Qtc29j/aWFsLXdpZGUuanBn",
          "original": "https://www.rust-lang.org/static/images/rust-social-wide.jpg"
        },
        "extra_snippets": [
          "Affectionately nicknamed “the book,” The Rust Programming Language will give you an overview of the language from first principles. You’ll build a few projects along the way, and by the end, you’ll have a solid grasp of the language. Read the Book! If reading multiple hundreds of pages about a language isn’t your style, then Rust By Example has you covered. While the book talks about code with a lot of words, RBE shows off a bunch of code, and keeps the talking to a minimum.",
          "Guide to the Rust editions. ... A book on Rust’s package manager and build system. ... Learn how to make awesome documentation for your crate.",
          "Familiarize yourself with the knobs available in the Rust compiler. ... In-depth explanations of the errors you may see from the Rust compiler. ... Learn how to build effective command line applications in Rust.",
          "All of this documentation is also available locally using the rustup doc command, which will open up these resources for you in your browser without requiring a network connection! ... Comprehensive guide to the Rust standard library APIs."
        ]
      },
      {
        "title": "How to Learn Rust in 2025: A Complete Beginner’s Guide to Mastering Rust Programming | The RustRover Blog",
        "url": "https://blog.jetbrains.com/rust/2024/09/20/how-to-learn-rust/",
        "description": "In many cases, Rust’s approach to asynchronous programming makes it possible to avoid using complex concurrency patterns and enables you to write concise and clear code. Although concurrency is not the first thing beginners learn when approaching Rust, it is still easier to grasp than in ...",
        "page_age": "February 5, 2026",
        "profile": {
          "name": "JetBrains"
        },
        "meta_url": {
          "favicon": "https://imgs.search.brave.com/IBVWg1JL11i7Qpeg_zwUsHD18OYjlFzBo1TL7231AxQ/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvZjljNmY2Yjdi/YjM3YWMzZGI5YTYz/ZjRjNGJhZGI2Njc5/ZWQ2NGM4ZTFkYTk3/OGMwZWE3YzNmNDI3/OWExZjBkYS9ibG9n/LmpldGJyYWlucy5j/b20v"
        },
        "thumbnail": {
          "src": "https://imgs.search.brave.com/JFxusCZ1WRBxzBLyAWQzJSwXEMg8jFGYh43jgMbvkJ0/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly9ibG9n/LmpldGJyYWlucy5j/b20vd3AtY29udGVu/dC91cGxvYWRzLzIw/MjQvMDkvcnItc29j/aWFsX3NoYXJlX2Js/b2dfMTI4MHg3MjBf/ZW4tMS5wbmc",
          "original": "https://blog.jetbrains.com/wp-content/uploads/2024/09/rr-social_share_blog_1280x720_en-1.png"
        },
        "extra_snippets": [
          "In many cases, Rust’s approach to asynchronous programming makes it possible to avoid using complex concurrency patterns and enables you to write concise and clear code. Although concurrency is not the first thing beginners learn when approaching Rust, it is still easier to grasp than in many other programming languages.",
          "So, you're thinking about choosing Rust as your next programming language to learn. You already know what it means to write code and have some experience with at least one programming language, probab",
          "So, you’re thinking about choosing Rust as your next programming language to learn. You already know what it means to write code and have some experience with at least one programming language, probably Python or JavaScript. You’ve heard about Rust here and there.",
          "People say it’s a modern systems programming language that brings safety and performance and solves problems that are hard to avoid in other programming languages (such as C or C++). Someone mentioned that Rust’s popularity is growing. You regularly see blog posts describing how Google, Microsoft, Amazon, and other big players in the field have already adopted it. Other mentions indicate that adoption in various industries is still growing. However, it’s also been whispered that Rust is not the easiest language to learn, so you worry about whether you can handle it."
        ]
      },
      {
        "title": "r/rust on Reddit: What do you think is the best way to learn Rust?",
        "url": "https://www.reddit.com/r/rust/comments/ngq5rs/what_do_you_think_is_the_best_way_to_learn_rust/",
        "description": "Is there a resource that starts with small projects and builds up as you progress? How do you come up with these projects? I agree that this is the best way to learn. ... I was playing around with https://exercism.io/my/tracks/rust and it's probably what I am looking for - creating small programs first and then more complex ones as you build your skills.....gonna give it a shot.",
        "page_age": "May 20, 2021",
        "profile": {
          "name": "Reddit"
        },
        "meta_url": {
          "favicon": "https://imgs.search.brave.com/U-eHNCapRHVNWWCVPPMTIvOofZULh0_A_FQKe8xTE4I/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvN2ZiNTU0M2Nj/MTFhZjRiYWViZDlk/MjJiMjBjMzFjMDRk/Y2IzYWI0MGI0MjVk/OGY5NzQzOGQ5NzQ5/NWJhMWI0NC93d3cu/cmVkZGl0LmNvbS8"
        },
        "thumbnail": {
          "src": "https://imgs.search.brave.com/6IlMzqfw8BQRYCgHyPxxMsE_r65r0H9dkVqdmY-pEYU/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly9zaGFy/ZS5yZWRkLml0L3By/ZXZpZXcvcG9zdC9u/Z3E1cnM",
          "original": "https://share.redd.it/preview/post/ngq5rs"
        },
        "extra_snippets": [
          "My exp is in web dev (PHP) but I wanted to learn a new language so I dove into Rust last month. Love the compiler and it is refreshing getting back to compiling code :) (started my career as a java programmer)",
          "They are all fully working programs. ... I learned Rust by rushing through the book as quickly as possible and then started writing a compiler.",
          "Is there a resource that starts with small projects and builds up as you progress? How do you come up with these projects? I agree that this is the best way to learn. ... I was playing around with https://exercism.io/my/tracks/rust and it's probably what I am looking for - creating small programs first and then more complex ones as you build your skills.....gonna give it a shot.",
          "It drives me crazy when juniors do copy & paste (aka cargo cult) programming, and asking me for help. ... this is the answer i am looking for but there's a little doubt (sorry for my bad english ) so suppose a very fresher want to start his programing journey with rust then what step he should need to take so that he can learn that language (i know rust book is great source) but when it comes to starting with litlle cozy projects so here how can we learn through this (i am very confused about it so you may be feel my answer like a random but it is what it is ) please help me"
        ]
      },
      {
        "title": "Introduction - A Gentle Introduction to Rust",
        "url": "https://stevedonovan.github.io/rust-gentle-intro/",
        "description": "I'd suggest you start out with basic syntax highlighting at first, and work up as your programs get larger. Personally I'm a fan of Geany which is one of the few editors with Rust support out-of-the-box; it's particularly easy on Linux since it's available through the package manager, but it ...",
        "page_age": "",
        "profile": {
          "name": "LDoc"
        },
        "meta_url": {
          "favicon": "https://imgs.search.brave.com/EflVyDUCUqYdyq5RHcpGxLcffTjqIKRixr60LjYUaU4/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvZmVjOTBkMjc1/Yzk3NzhmMzA1ZTc0/YjM5ZDUwNGI2YjRk/YWNlOGVmZGY0NjU2/YjQ0MzdkMjk3MTJi/ODg2ZmIzOC9zdGV2/ZWRvbm92YW4uZ2l0/aHViLmlvLw"
        },
        "extra_snippets": [
          "However, it's actually a very pleasant language to write normal application code in as well. The big difference from C and C++ is that Rust is safe by default; all memory accesses are checked. It is not possible to corrupt memory by accident. ... There is a fast-growing ecosystem of available libraries through Cargo but here we will concentrate on the core principles of the language by learning to use the standard library. My advice is to write lots of small programs, so learning to use rustc directly is a core skill.",
          "I'd suggest you start out with basic syntax highlighting at first, and work up as your programs get larger. Personally I'm a fan of Geany which is one of the few editors with Rust support out-of-the-box; it's particularly easy on Linux since it's available through the package manager, but it works fine on other platforms. The main thing is knowing how to edit, compile and run Rust programs. You learn to program with your fingers; type in the code yourself, and learn to rearrange things efficiently with your editor.",
          "He says learning to program is like learning a musical instrument - the secret is practice and persistence. There's also good advice from Yoga and the soft martial arts like Tai Chi; feel the strain, but don't over-strain. You are not building dumb muscle here. I'd like to thank the many contributors who caught bad English or bad Rust for me, and thanks to David Marino for his cool characterization of Rust as a friendly-but-hardcore no-nonsense knight in shining armour.",
          "There will be some uphill but the view will be inspiring; the community is unusually pleasant and happy to help. There is the Rust Users Forum and an active subreddit which is unusually well-moderated. The FAQ is a good resource if you have specific questions. First, why learn a new programming language?"
        ]
      }
    ]
  },
  {
    "id": "store-example-web-search-2",
    "query": "best noise cancelling headphones 2026",
    "query_translation_key": "settings.app_store_examples.web.search.2",
    "provider": "Brave Search",
    "status": "finished",
    "results": [
      {
        "title": "The 5 Best Noise Cancelling Headphones of 2026 - RTINGS.com",
        "url": "https://www.rtings.com/headphones/reviews/best/by-feature/noise-cancelling",
        "description": "The Sony WH-1000XM6 are the best noise cancelling headphones we've tested. These premium over-ears have remarkable noise isolation.",
        "page_age": "3 weeks ago",
        "profile": {
          "name": "RTINGS"
        },
        "meta_url": {
          "favicon": "https://imgs.search.brave.com/h-NpJKP6ACR7LmAyOrQNOgLZ3sxqhz-nyHSy-_lSdJQ/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvY2ZkN2UzZTE3/NDJjZWZlZGVhZjZi/YTJmZjA4NzBiNzBh/ZDJmY2RiNmQzZmZh/MTZkYTNhYjk4NWE4/MmI2ZDQ0NS93d3cu/cnRpbmdzLmNvbS8"
        },
        "thumbnail": {
          "src": "https://imgs.search.brave.com/_cB_PU1W1SaBv_7H3U5hw59PzeDWPYPmOyv35VnyCPs/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly9pLnJ0/aW5ncy5jb20vYXNz/ZXRzL3BhZ2VzL0tt/NnVBcGM5L2Jlc3Qt/bm9pc2UtY2FuY2Vs/bGluZy1oZWFkcGhv/bmVzLTIwMjMwOTA2/LW1lZGl1bS5qcGc_/Zm9ybWF0PWF1dG8",
          "original": "https://i.rtings.com/assets/pages/Km6uApc9/best-noise-cancelling-headphones-20230906-medium.jpg?format=auto"
        },
        "extra_snippets": [
          "Headphones Noise Cancelling Wireless Earbuds Gaming Over-Ear Noise Cancelling Earbuds Wireless Running Apple Wireless Gaming PC Gaming Bone Conduction And Open-Ear Wired Xbox Series X/S In-Ears On-Ear Wireless Earbuds For Android Music PS5/PS5 Pro Budget And Cheap"
        ]
      },
      {
        "title": "Best noise-cancelling headphones 2026 – tested by our in-house review experts | What Hi-Fi?",
        "url": "https://www.whathifi.com/best-buys/headphones/best-noise-cancelling-headphones",
        "description": "Best Bose3. Bose QuietComfort Ultra Headphones (2nd Gen) ☆☆☆☆☆Noise cancellation up there with the bestRead more▼",
        "page_age": "January 9, 2026",
        "profile": {
          "name": "What Hi-Fi?"
        },
        "meta_url": {
          "favicon": "https://imgs.search.brave.com/_CWdnveXEJav1lDgUUeVe2nV806M3ziUJLSU1uYv5GE/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvZWU1NTgyNjdj/ZDc0M2MwNmNlNjU3/NmM1ODVkM2I3Yzg5/MWY4ZGM3MTM2ZDFj/ZjA0NWYzYTQ0MmU1/NTFjN2QwNi93d3cu/d2hhdGhpZmkuY29t/Lw"
        },
        "thumbnail": {
          "src": "https://imgs.search.brave.com/yj9amNIDGQY7JC9c3smVjVniqoa0BdKJMQMiO8RLl5s/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly9jZG4u/bW9zLmNtcy5mdXR1/cmVjZG4ubmV0L1pW/TjJ4RTducWhCVE1G/Sm52WGd3dmgtMTky/MC04MC5qcGc",
          "original": "https://cdn.mos.cms.futurecdn.net/ZVN2xE7nqhBTMFJnvXgwvh-1920-80.jpg"
        },
        "extra_snippets": [
          "Every pair on this page has impressed our expert testers in every department and represents the very best of its kind at its price. ... 9th January 2026: Replaced Bose QuietComfort Ultra Headphones with newer 2nd Gen model. Added Sennheiser HDB 630 to 'Also consider' section following our review. ... I've been writing for What Hi-Fi? for a decade now, with over another decade's experience on other tech titles prior to that. In my 20+ years in the industry, I've covered all kinds of noise-cancelling headphones.",
          "But certainly, like with any headphones, you shouldn't listen at loud volumes for a long time. However, if anything, noise-cancelling headphones will allow you to listen at lower volumes, as you don't need to turn the volume up to counter outside noise. January 2026: Replaced Bose QuietComfort Ultra Headphones with 2nd Gen model.",
          "Best Bose3. Bose QuietComfort Ultra Headphones (2nd Gen) ☆☆☆☆☆Noise cancellation up there with the bestRead more▼",
          "Our in-house review experts have tested hundreds of ANC headphones since the first pair from 'noise-cancelling king' Bose broke new ground three decades ago, and our six picks below represent the very best you can buy at their various price points."
        ]
      },
      {
        "title": "r/SonyHeadphones on Reddit: Best Noise Cancelling Headphones to Buy In 2026? (Price, Sound)",
        "url": "https://www.reddit.com/r/SonyHeadphones/comments/1rtlj4f/best_noise_cancelling_headphones_to_buy_in_2026/",
        "description": "... Yo ya probé todos los últimos lanzamientos: xm6, freebuds pro 5, galaxy buds 4pro, bose qc ultra 2. Excepto los airpods (tengo android) Y la neta, si solo buscas la mejor cancelación de ruido con buen sonido en general, esa la tienen ...",
        "page_age": "3 weeks ago",
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
          "41 votes, 49 comments. Hey guys, I work remote so I move around a lot and I was browsing Reddit to see what people here suggest for good ANC…",
          "Posted by u/JeanetteAGalbreat - 41 votes and 49 comments",
          "Came to this thread after googling 'best headphones to buy 2026' because the hinge on my XM5's just snapped after taking them off. Bought them less than a year ago.",
          "just a quick remark: asking for what is the best in 2026, when only mid march 2026, feels a little silly. ... Yo ya probé todos los últimos lanzamientos: xm6, freebuds pro 5, galaxy buds 4pro, bose qc ultra 2. Excepto los airpods (tengo android) Y la neta, si solo buscas la mejor cancelación de ruido con buen sonido en general, esa la tienen los bose qc ultra 2."
        ]
      },
      {
        "title": "The 4 Best Noise-Cancelling Headphones of 2026 | Reviews by Wirecutter",
        "url": "https://www.nytimes.com/wirecutter/reviews/best-noise-cancelling-headphones/",
        "description": "The Sony WH-1000XM6 headphones offer an excellent combination of noise reduction, comfort, and sound quality in a lightweight design that’s great for travel. Although the WH-1000XM6’s active noise cancellation is a few decibels shy of the ...",
        "page_age": "1 week ago",
        "profile": {
          "name": "NYTimes"
        },
        "meta_url": {
          "favicon": "https://imgs.search.brave.com/lWA-zkTMlWM2cUvrcYa1Fls86e-Vl-rkSBOjichQqVs/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvMGFlZWRkYmVh/YWFhZmFjYjM4MWYy/NTQzZmExMTIwN2Nm/NGJmZjgwYTRhYjI5/OTliM2JkYmI2MWY0/M2RlOGFlMi93d3cu/bnl0aW1lcy5jb20v"
        },
        "thumbnail": {
          "src": "https://imgs.search.brave.com/NLZCpfiMaoxveyc8yLsXJZ725PatoSoICUa1CfDlT2k/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly9jZG4u/dGhld2lyZWN1dHRl/ci5jb20vd3AtY29u/dGVudC9tZWRpYS8y/MDI1LzA1L0JFU1Qt/Tk9JU0UtQ0FOQ0VM/TElORy1IRUFEUEhP/TkVTLTgyNDYtM3gy/LTEuanBnP2F1dG89/d2VicCZxdWFsaXR5/PTc1JmNyb3A9MTox/LHNtYXJ0JndpZHRo/PTEwMjQ",
          "original": "https://cdn.thewirecutter.com/wp-content/media/2025/05/BEST-NOISE-CANCELLING-HEADPHONES-8246-3x2-1.jpg?auto=webp&quality=75&crop=1:1,smart&width=1024"
        },
        "extra_snippets": [
          "We tested Apple’s new AirPods Max 2 and added them to Other noise-cancelling headphones worth considering.April 2026",
          "It’s a popular misconception that ANC headphones cancel out all noises equally. They don’t. Active noise cancellation is generally more effective on lower frequencies of sound, such as the hum of a jet engine or an air conditioner. It’s not as successful with human voices and other higher frequencies. The technology never works perfectly, but it can work well enough in certain environments to make listening more enjoyable. The best noise-cancelling headphones combine this “active” noise cancelling with passive noise reduction — that is, physical barriers and dampers built into the headphones that help block or absorb noise.",
          "The Sony WH-1000XM6 headphones offer an excellent combination of noise reduction, comfort, and sound quality in a lightweight design that’s great for travel. Although the WH-1000XM6’s active noise cancellation is a few decibels shy of the best reduction we’ve measured in the airplane band (see the chart in How we picked and tested), it’s still up there among the top performers.",
          "Right out of the box, it sounds incredible — among the best we’ve tested. Most people are likely to be thrilled by the clarity of the highs, which were not piercing or harsh in our tests. Bass notes sounded pure, not smeared or boomy. I heard a little less detail and sense of space through these headphones compared with the Stax Spirit S3, but that pair lacks noise cancellation and generally isn’t as full-featured."
        ]
      }
    ]
  },
  {
    "id": "store-example-web-search-3",
    "query": "latest james webb space telescope discoveries",
    "query_translation_key": "settings.app_store_examples.web.search.3",
    "provider": "Brave Search",
    "status": "finished",
    "results": [
      {
        "title": "Hubble News - NASA Science",
        "url": "https://science.nasa.gov/mission/hubble/hubble-news/",
        "description": "Captured Aug. 22, 2024 by NASA’s Hubble Space Telescope, this visible-light view of Saturn reveals the planet’s softly banded atmosphere… ... A wider view of Saturn from NASA’s James Webb Space Telescope shows six of Saturn’s larger moons, including the largest,…",
        "page_age": "January 16, 2026",
        "profile": {
          "name": "NASA Science"
        },
        "meta_url": {
          "favicon": "https://imgs.search.brave.com/geuh6TdxVQzGteV-sKQncNta5ZuEqFM_qf_N6SmH1ZY/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvMDVlZjkwZjVi/MmJmMDQ4N2E0MWYz/NmZmYjhiNWUyNWJk/ODhkOTA0MmIyNDBj/MWQ4ODRjMDJjZDJl/ZjcyNGUxYy9zY2ll/bmNlLm5hc2EuZ292/Lw"
        },
        "thumbnail": {
          "src": "https://imgs.search.brave.com/hXE5HijdNdNL1Vi0EEgMz6cgNVZz2RqUxnTvjyv0Ctc/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly9zY2ll/bmNlLm5hc2EuZ292/L3dwLWNvbnRlbnQv/dXBsb2Fkcy8yMDI0/LzEwL2h1YmJsZS1y/YXF1YXJpaS1zdHNj/aS0wMWo4MGI1cDBx/ZnNyem45YTJlNDhm/NjFjeC5qcGc",
          "original": "https://science.nasa.gov/wp-content/uploads/2024/10/hubble-raquarii-stsci-01j80b5p0qfsrzn9a2e48f61cx.jpg"
        },
        "extra_snippets": [
          "Astronomers using NASA’s Hubble Space Telescope have found evidence that the spinning of a small comet slowed and then reversed… ... This artist’s concept depicts comet 41P, a tiny Jupiter-family comet, as it approached the Sun and frozen gases began to… ... This artist’s concept depicts comet 41P as it approached the Sun and frozen gases began to sublimate off the comet’s… ... NASA’s James Webb Space Telescope and Hubble Space Telescope have teamed up to capture new views of Saturn, revealing the…",
          "Captured Aug. 22, 2024 by NASA’s Hubble Space Telescope, this visible-light view of Saturn reveals the planet’s softly banded atmosphere… ... A wider view of Saturn from NASA’s James Webb Space Telescope shows six of Saturn’s larger moons, including the largest,…",
          "Captured Nov. 29, 2024 by NASA’s James Webb Space Telescope, this infrared view of Saturn shows its glowing icy rings…",
          "Complementary views of Saturn from NASA’s James Webb Space Telescope and Hubble Space Telescope show a dynamic planet with atmospheric…"
        ]
      },
      {
        "title": "Strange cosmic objects spotted by the James Webb Space Telescope may be baby 'platypus' galaxies — or something entirely new | Space",
        "url": "https://www.space.com/astronomy/galaxies/strange-cosmic-objects-spotted-by-the-james-webb-space-telescope-may-be-baby-platypus-galaxies-or-something-entirely-new",
        "description": "James Webb Space Telescope The James Webb Space Telescope just mapped auroras on Uranus in 3D for the 1st time, and scientists are thrilled · Stars Two stars carve egg-shaped nebula | Space photo of the day Feb.",
        "page_age": "January 9, 2026",
        "profile": {
          "name": "Space.com"
        },
        "meta_url": {
          "favicon": "https://imgs.search.brave.com/3XCWt_c3BOddJsusRhNQvWZ04Lxr1r3p5zwYi96n5Pw/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvYjQ1NzY5OGQ2/YmQ3ODRkMDExMjg1/NzJhMTQyZWI3NmQ5/ZDhkNDkzNGZlNGJj/MGRmNmVhNTAyOWRm/ZmQxYWM3Mi93d3cu/c3BhY2UuY29tLw"
        },
        "thumbnail": {
          "src": "https://imgs.search.brave.com/CotZrmkWh8fdZx4kQEIq15QpECRZUyVkAqLjc_wMaUQ/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly9jZG4u/bW9zLmNtcy5mdXR1/cmVjZG4ubmV0L0Vx/TDJXQXZCVkNTWUFl/QldWdlRTV1ktMTky/MC04MC5qcGc",
          "original": "https://cdn.mos.cms.futurecdn.net/EqL2WAvBVCSYAeBWVvTSWY-1920-80.jpg"
        },
        "extra_snippets": [
          "James Webb Space Telescope The James Webb Space Telescope just mapped auroras on Uranus in 3D for the 1st time, and scientists are thrilled · Stars Two stars carve egg-shaped nebula ",
          " Space photo of the day Feb. 24, 2026 · Black Holes Astronomers witness vanishing star collapse into a black hole in Andromeda galaxy · Astronomy 8 astronomy discoveries that wowed us in 2025",
          "James Webb Space Telescope's mysterious 'little red dots' may be black holes in disguise · What are 'dark' stars? Scientists think they could explain 3 big mysteries in the universe · Soon after JWST saw first light in 2021, it began to reveal a number of unusual objects of unknown origin. Inspired by these discoveries, Yan and two of his students began to explore other compact sources in a quest to determine if any strange objects had escaped notice.",
          "Strange cosmic objects spotted by NASA's James Webb Space Telescope (JWST) are presently puzzling astronomers as they show features of both stars and galaxies.",
          "The James Webb Space Telescope recently captured these strange cosmic objects. (Image credit: NASA, ESA, CSA, S. Finkelstein (UT Austin), Image Processing: A. Pagan (STScI)) ... Breaking space news, the latest updates on rocket launches, skywatching events and more!"
        ]
      },
      {
        "title": "These are the most important discoveries of the James Webb telescope that you won’t believe - AS USA",
        "url": "https://en.as.com/latest_news/these-are-the-most-important-discoveries-of-the-james-webb-telescope-that-you-wont-believe-n/",
        "description": "The James Webb telescope has only been on the job for a relatively short time, but it has already made spectacular discoveries and taken stunning photos. ... Christmas Day 2021, the James Webb Space Telescope took off from French Guiana aboard an Ariane 5 rocket.",
        "page_age": "February 9, 2024",
        "profile": {
          "name": "AS USA"
        },
        "meta_url": {
          "favicon": "https://imgs.search.brave.com/VwWMoJOAVmM_23axIG3yw8edZfN-jkoo8n-p_RGYBAw/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvODdmODFkMWEw/YTM1NjRhMzRmOTZl/NzY1MzdmOGVkMTYx/YmQ4NzBiNjU3NDdk/MDIyNjAwNmFjMmEy/MjljOTEyNS9lbi5h/cy5jb20v"
        },
        "thumbnail": {
          "src": "https://imgs.search.brave.com/uY_UXqhIg8Yia9QCQiiOL6jTSNvfdYq8toFIXyuXbsc/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly9pbWcu/YXNtZWRpYS5lcGlt/Zy5uZXQvcmVzaXpl/ci92Mi9ZUEU3UzU0/SVQ1RUZWSlNYMkdJ/R0dJTFVLRS5qcGc_/YXV0aD1iMjU5NTA1/YzllNjZlZTMxZGI3/ZmYzZTU1ODc3ZTYz/N2U0NzIzZmMwMWYx/MmNlZGVjMDA5YTdi/ZmQyNTM0MWIxJndp/ZHRoPTE0NzImaGVp/Z2h0PTgyOCZzbWFy/dD10cnVl",
          "original": "https://img.asmedia.epimg.net/resizer/v2/YPE7S54IT5EFVJSX2GIGGILUKE.jpg?auth=b259505c9e66ee31db7ff3e55877e637e4723fc01f12cedec009a7bfd25341b1&width=1472&height=828&smart=true"
        },
        "extra_snippets": [
          "However, once it began work, it has been dazzling scientists and the public alike with spectacular discoveries and stunning photos. “The James Webb Space Telescope is a giant leap forward in our quest to understand the Universe and our origins,” states NASA.",
          "In order to understand the origins of life, scientists have been keen to discover evidence of the building blocks of life such as water and carbon molecules as well as understanding how planets form. The James Webb Space Telescope has made spectacular discoveries on all of these fronts.",
          "The James Webb Space Telescope has also upended what we know about the formation of galaxies. It was thought that they couldn’t take on the telltale shapes that we see today like bars, rings or spiral arms until about 6 billion years after the Big Bang. However, images that have been captured show advanced structures when the universe was possibly less than half that age. Follow all the latest news on AS USA.",
          "The multi-billion-dollar telescope is able to peer deep into space and back in time to a few hundred million years after the big bang. Its 6.5-meter telescope also has the capability to observe with far greater detail than ever before the galaxies, nebula, stars and planets that make up our universe. Here are some of the spectacular accomplishments the James Webb Space Telescope can brag about and making astronomers rethink what they knew about the universe and everything in it."
        ]
      },
      {
        "title": "Latest Discoveries made by the James Webb Space Telescope - March 2024 Edition",
        "url": "https://blog.jameswebbdiscovery.com/2024/03/latest-discoveries-made-by-james-webb.html",
        "description": "By dissecting the light from the star-forming region NGC 604, Webb revealed never-before-seen structures and objects, giving us a deeper look into stellar nurseries. https://www.jameswebbdiscovery.com/discoveries/james-webb-telescope-sheds-...",
        "page_age": "March 23, 2024",
        "profile": {
          "name": "Jameswebbdiscovery"
        },
        "meta_url": {
          "favicon": "https://imgs.search.brave.com/fTPEsZWN4AII4LTDjUGrpTiQpk-348z2MAVY0Tgiauw/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvNGQyMmYzMjk4/MGRhM2I0NjZiYTFh/Zjg0YTU5Mjc3Y2Rl/MTIzMmJjYjBjOTgy/NTI0NTg1NGQ3NjRl/MDU5YWNlYi9ibG9n/LmphbWVzd2ViYmRp/c2NvdmVyeS5jb20v"
        },
        "thumbnail": {
          "src": "https://imgs.search.brave.com/WUehjTAaji0WHka4mjzQkWE6JPHZipEFOpn-skdAqMo/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly9ibG9n/Z2VyLmdvb2dsZXVz/ZXJjb250ZW50LmNv/bS9pbWcvYi9SMjl2/WjJ4bC9BVnZYc0Vn/U1k1S3VhR25DQ0JN/RWJ2bVZsTE1RMmRG/cno0aGpDQ2I0VUtQ/dl9qSHo0R0JGbWZo/WUExaFowX1BYQVlR/U00tdlNWX2Z0QnJ3/Q1dDdzFwMjl0a1Fq/UktxT1ZiUFJFeXAt/b0FqNEE3N0hHNmxJ/Wm1GUVh4dGJoMVpj/Y2o0MzRUMkZCclZz/R25Ra19QYmV1X2NN/UmZiZ3RrUHlrMVZI/WTNMOEpCNXFQTTFK/SDBKMkVNUTJHQzA3/THl0WTlTX2cvdzEy/MDAtaDYzMC1wLWst/bm8tbnUvTkdDLTYw/NC1oZWFkLnBuZw",
          "original": "https://blogger.googleusercontent.com/img/b/R29vZ2xl/AVvXsEgSY5KuaGnCCBMEbvmVlLMQ2dFrz4hjCCb4UKPv_jHz4GBFmfhYA1hZ0_PXAYQSM-vSV_ftBrwCWCw1p29tkQjRKqOVbPREyp-oAj4A77HG6lIZmFQXxtbh1Zccj434T2FBrVsGnQk_Pbeu_cMRfbgtkPyk1VHY3L8JB5qPM1JH0J2EMQ2GC07LytY9S_g/w1200-h630-p-k-no-nu/NGC-604-head.png"
        },
        "extra_snippets": [
          "By dissecting the light from the star-forming region NGC 604, Webb revealed never-before-seen structures and objects, giving us a deeper look into stellar nurseries. https://www.jameswebbdiscovery.com/discoveries/james-webb-telescope-sheds-light-on-the-chaotic-cradle-of-stars-in-ngc-604 · These discoveries are just the beginning. As Webb continues its mission, expect even more groundbreaking revelations about the universe's origins, evolution, and potential for life. Stay tuned for future updates on humanity's incredible journey to unravel the cosmic mysteries! Check out the James Webb Space Telescope Discoveries Tracker for all the discoveries made by this engineering marvel.",
          "The James Webb Space Telescope (JWST), humanity's most powerful observatory, continues to revolutionize our understanding of the cosmos. Here's a glimpse into Webb's latest discoveries from March 2024:",
          "Webb peered into the heart of a recent supernova remnant, SN 1987A, and found strong evidence for a hidden neutron star. This discovery helps us piece together the violent life cycle of massive stars. https://www.jameswebbdiscovery.com/discoveries/james-webb-telescope-detects-neutron-star-in-supernova-remnant-sn-1987a",
          "These faint, cool objects lack the nuclear fusion needed to be stars. The auroras hint at a dynamic atmosphere on the brown dwarf, fueled by unknown processes. https://www.jameswebbdiscovery.com/discoveries/james-webb-telescope-unearths-auroral-activity-on-brown-dwarf-w1935"
        ]
      }
    ]
  }
];

export default examples;
