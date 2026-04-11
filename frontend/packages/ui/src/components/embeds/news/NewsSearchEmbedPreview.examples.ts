/**
 * App-store examples for the news/search skill.
 *
 * Captured from real Brave news search responses, trimmed to 4 results per query.
 *
 * Each example includes an optional `query_translation_key` that
 * SkillExamplesSection resolves via the i18n store at render time, so
 * the card label is localised while the raw provider data stays
 * authentic.
 */

export interface NewsSearchStoreExample {
  id: string;
  query: string;
  query_translation_key: string;
  provider: string;
  status: 'finished';
  results: Array<Record<string, unknown>>;
}

const examples: NewsSearchStoreExample[] = [
  {
    "id": "store-example-news-search-1",
    "query": "ai breakthroughs 2026",
    "query_translation_key": "app_store_examples.news.search.1",
    "provider": "Brave Search",
    "status": "finished",
    "results": [
      {
        "title": "National Robotics Week — Latest Physical AI Research, Breakthroughs and Resources | NVIDIA Blog",
        "url": "https://blogs.nvidia.com/blog/national-robotics-week-2026/",
        "description": "https://blogs.nvidia.com/wp-content/uploads/2026/04/Aigen_Element_Weeding_1.mp4 · Using these rovers, farmers can grow crops more sustainably and profitably, using regenerative practices that heal the land and foster ecological balance. Learn about the breakthroughs shaping the next chapter ...",
        "page_age": "1 day ago",
        "meta_url": {
          "favicon": "https://imgs.search.brave.com/uXXUVdr65BSph8FL_3ZwQaSgrOFgnsLZK3u7_AAON3g/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvNmU3OTFmOTkw/YWJkMzhiZTcwZjdk/MDE4ZTc5MWQxN2Zj/ZjMwYzA2ZjA1NWYy/MDBlNDFiNmZhYjBm/YWIxMWFkMy9ibG9n/cy5udmlkaWEuY29t/Lw"
        },
        "thumbnail": {
          "src": "https://imgs.search.brave.com/nOZqCgHoiAwfkIdRkK7_BCWreSo2mCP1oERNeqrl0cc/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly9ibG9n/cy5udmlkaWEuY29t/L3dwLWNvbnRlbnQv/dXBsb2Fkcy8yMDI2/LzA0L3JvYm90aWNz/LXRlY2gtYmxvZy1u/cnctcm9sbGluZy1i/bG9nLTEyODB4Njgw/LTEuanBn"
        },
        "extra_snippets": [
          "https://blogs.nvidia.com/wp-content/uploads/2026/04/Aigen_Element_Weeding_1.mp4 · Using these rovers, farmers can grow crops more sustainably and profitably, using regenerative practices that heal the land and foster ecological balance. Learn about the breakthroughs shaping the next chapter of AI anytime, anywhere.",
          "At NVIDIA GTC last month, a new wave of technologies was introduced to accelerate the development of AI-powered robots. At the core is a full-stack, cloud-to-robot workflow that connects simulation, robot learning and edge computing — making it faster to build, train and deploy intelligent machines. https://blogs.nvidia.com/wp-content/uploads/2026/04/GTC26-Robots_16x9_v3-2-1.mp4",
          "This integration lets developers easily develop and deploy embodied AI techniques for underwater applications. RoboLab is a high-fidelity simulation benchmark for developing and evaluating generalist robot policies — powering systems designed to perform diverse tasks across environments. https://blogs.nvidia.com/wp-content/uploads/2026/04/Put_the_onion_in_the_wood_bowl_0_viewport_3X.mp4",
          "This National Robotics Week, NVIDIA is highlighting the breakthroughs that are bringing AI into the physical world — as well as the growing wave of robots transforming industries, from agricultural and manufacturing to energy and beyond."
        ]
      },
      {
        "title": "AI breakthrough cuts energy use by 100x while boosting accuracy | ScienceDaily",
        "url": "https://www.sciencedaily.com/releases/2026/04/260405003952.htm",
        "description": "Retrieved April 5, 2026 from www.sciencedaily.com ... Tufts University. \"AI breakthrough cuts energy use by 100x while boosting accuracy.\" ScienceDaily.",
        "page_age": "6 days ago",
        "meta_url": {
          "favicon": "https://imgs.search.brave.com/foZWtSo3V3W24ojU_8gmckPVnJXm8Syx_9jXzX6MPR0/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvYmM2ZmUzNWRm/MGU5YmQyYjQxMDk0/YzMzMmVhYzc1YjE3/NmYzMGRjODIyOGVj/NGE3ZDhiZGQ5NTc3/YTI3NTUzYi93d3cu/c2NpZW5jZWRhaWx5/LmNvbS8"
        },
        "thumbnail": {
          "src": "https://imgs.search.brave.com/2k_6iXaPNhfbPrKUhFo5d0b8huGItRIwDbsGMyhGgJY/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly93d3cu/c2NpZW5jZWRhaWx5/LmNvbS9pbWFnZXMv/MTkyMC9zZXJ2ZXIt/ZmFjaWxpdHktYXQt/c2FuZGlhLW5hdGlv/bmFsLWxhYm9yYXRv/cnkud2VicA"
        },
        "extra_snippets": [
          "Tufts University. (2026, April 5). AI breakthrough cuts energy use by 100x while boosting accuracy. ScienceDaily.",
          "AI is consuming staggering amounts of energy—already over 10% of U.S. electricity—and the demand is only accelerating. Now, researchers have unveiled a radically more efficient approach that could slash AI energy use by up to 100× while actually improving accuracy.",
          "The Price Is Not Right: Neuro-Symbolic Methods Outperform VLAs on Structured Long-Horizon Manipulation Tasks with Significantly Lower Energy Consumption. arXiv, 22 Feb 2026 DOI: https://arxiv.org/abs/2602.19260 ... Tufts University. \"AI breakthrough cuts energy use by 100x while boosting accuracy.\"",
          "Ant Insights Lead to Robot Navigation Breakthrough · July 17, 2024  Have you ever wondered how insects are able to go so far beyond their home and still find their way? The answer to this question is not only relevant to biology but also to making the AI for tiny, ..."
        ]
      },
      {
        "title": "Time",
        "url": "https://time.com/article/2026/04/07/ai-quantum-computing-advance/",
        "description": "Huang—who previously worked at Google Quantum AI and left in 2026 to work at Caltech and co-found Oratomic with some of the paper co-authors—told a friend at Google’s quantum initiative that he had been using AI and “seeing lots of crazy results.” A few months later, in early March, ...",
        "page_age": "4 days ago",
        "meta_url": {
          "favicon": "https://imgs.search.brave.com/nfd5JuER7u0mjyEPk1ytIw4_qGaihXtj6okMjkW62TE/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvMWRkMzU3NTQy/ZTI0OTAwYTdmOWY0/MzAyZTRmZTcyOGY3/OTcyMGM2OGNjYThk/YjRiZDUxN2NmYmYz/MmY0MzcxZi90aW1l/LmNvbS8"
        },
        "extra_snippets": [
          "Huang—who previously worked at Google Quantum AI and left in 2026 to work at Caltech and co-found Oratomic with some of the paper co-authors—told a friend at Google’s quantum initiative that he had been using AI and “seeing lots of crazy results.” A few months later, in early March, Google posted a job for a quantum researcher to develop AI-based “discovery pipelines.”",
          "AI was “instrumental” in developing the Oratomic team’s algorithm, the paper’s authors tell TIME. “There is no question that we used AI to accelerate this development,” says Dolev Bluvstein, one of the paper’s authors.",
          "AI leaders have repeatedly promised that AI would accelerate scientific progress. “The gains to quality of life from AI driving faster scientific progress … will be enormous,” wrote Sam Altman in 2025. Beyond cracking encryption protocols, quantum computing researchers hope the new technology could help make discoveries in physics, and design new drugs and materials.",
          "Without the AI, he says, it’s likely that he and his team would have tried a few ideas, seen that they didn’t work and decided that “the whole thing is not possible.” The AI’s proposals ended up significantly improving the performance of some of the most important algorithms in the paper."
        ]
      },
      {
        "title": "2026 is Breakthrough Year for Reliable AI World Models and Continual Learning Prototypes | NextBigFuture.com",
        "url": "https://www.nextbigfuture.com/2026/04/2026-is-breakthrough-year-for-reliable-ai-world-models-and-continual-learning-prototypes.html",
        "description": "Demis Hassabis (DeepMind CEO) and other AI leaders sees the next big AI gains—and the path to AGI—will come from targeted algorithmic breakthroughs in areas",
        "page_age": "1 day ago",
        "meta_url": {
          "favicon": "https://imgs.search.brave.com/Fjd4A1jwZTTMObvui54bUA61nTCzw4N-mZERM_F3vJg/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvYzBkYzZkNGRh/MzU1NjYzODE5MDEz/NGY4NzRjMjEyOTk1/ZmEwNDMxMDcyYTY1/YzQ2MTQ0MGM3ZTUz/NmI1YjNiNC93d3cu/bmV4dGJpZ2Z1dHVy/ZS5jb20v"
        },
        "thumbnail": {
          "src": "https://imgs.search.brave.com/_Xz-StnqeYXvRN05u18iQ96-Da-kxEB_dy_rbhawSN8/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly9uZXh0/YmlnZnV0dXJlLnMz/LmFtYXpvbmF3cy5j/b20vdXBsb2Fkcy8y/MDI2LzA0L1NjcmVl/bnNob3QtMjAyNi0w/NC0xMC1hdC0xMi4x/MS4xOC1QTS5qcGc"
        },
        "extra_snippets": [
          "\\Demis Hassabis (DeepMind CEO) and other AI leaders sees the next big AI gains—and the path to AGI—will come from targeted algorithmic breakthroughs in areas like continual learning, memory architectures, world models, reasoning/planning, and hybrid systems. Demis talked in a 20VC podcast with Harry Stebbings. Here’s a structured summary drawn from that interview, his other 2025–2026 statements (podcasts, DeepMind announcements), and the frontier research landscape.",
          "– 2026 Breakthrough year for reliable world models + continual learning prototypes. Expect interactive Genie-like systems in agents/robotics (real-time physics simulation for training embodied AI).",
          "Scaling buys time and capability, but the algorithmic innovations (Nested Learning, Titans/Hope, Genie 3, inference-time reasoning) are the real accelerators for 2026–2028. The AI trajectory matches Hassabis’ push both branches (scaling and algorithms) hard philosophy.",
          "2. Key frontier papers & improvements (2025–early 2026) Research has accelerated exactly in the areas Hassabis flags. AI is moving beyond static transformers to dynamic, memory-augmented, self-modifying, and world-simulating systems. Gains are algorithmic efficiency, new inductive biases."
        ]
      }
    ]
  },
  {
    "id": "store-example-news-search-2",
    "query": "climate policy europe",
    "query_translation_key": "app_store_examples.news.search.2",
    "provider": "Brave Search",
    "status": "finished",
    "results": [
      {
        "title": "A Tribute to Dr. Benny Peiser: Guardian of Reasonable in the Climate Policy Debate",
        "url": "https://stephenheins.substack.com/p/a-tribute-to-dr-benny-peiser-guardian",
        "description": "What it does not capture is his quiet determination, intellectual rigor, and unwavering commitment to evidence-based discourse that defined his tenure. At a time when climate policy often veered into dogma, Peiser stood as a steadfast European advocate for balance, moderation, and realism, ...",
        "page_age": "1 day ago",
        "meta_url": {
          "favicon": "https://imgs.search.brave.com/RBu1UDMtSSBMJodD9K59MyT9FmK4q5vk1RC6Mtrtfpk/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvZWU0NzA0ZTBk/M2EzYTk2ZmYyNGU5/ZjVjMWUwNWIwODU5/ZTg2ZGRiZGM5MzA5/NGM3NzlkMTBkZDhh/YjM4YTQzNC9zdGVw/aGVuaGVpbnMuc3Vi/c3RhY2suY29tLw"
        },
        "thumbnail": {
          "src": "https://imgs.search.brave.com/D7SmDVWGDT6qJJj2IWyScR4F1uNMPIvKz1Ro_PZHsTM/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly9zdWJz/dGFja2Nkbi5jb20v/aW1hZ2UvZmV0Y2gv/JHNfIU9jdG8hLHdf/MTIwMCxoXzY3NSxj/X2ZpbGwsZl9qcGcs/cV9hdXRvOmdvb2Qs/ZmxfcHJvZ3Jlc3Np/dmU6c3RlZXAsZ19h/dXRvL2h0dHBzJTNB/JTJGJTJGc3Vic3Rh/Y2stcG9zdC1tZWRp/YS5zMy5hbWF6b25h/d3MuY29tJTJGcHVi/bGljJTJGaW1hZ2Vz/JTJGYTUwNWJlYzYt/NzE5Mi00ZDk0LWE2/NmEtMDU5OTQ0MjU5/N2Q4XzU1M3g1NTQu/anBlZw"
        },
        "extra_snippets": [
          "What it does not capture is his quiet determination, intellectual rigor, and unwavering commitment to evidence-based discourse that defined his tenure. At a time when climate policy often veered into dogma, Peiser stood as a steadfast European advocate for balance, moderation, and realism, all very English.",
          "As he reflected in a farewell interview, the GWPF began as “lone voices in the wilderness,” warning of economic and political mistakes made from unilateral Western climate policies. Fifteen years later, many of those warnings have come to pass: Europe’s industrial challenges, failed green promises, and a growing political backlash against dogmatic targets.",
          "He has authored and oversaw dozens of reports, briefings, and lectures that highlighted the real-world costs of rushed decarbonization: soaring energy prices, fuel poverty, industrial decline in Europe, and the impracticality of aggressive Net Zero timelines. He testified before the U.S. Senate Committee on Environment and Public Works, addressed international conferences, and engaged policymakers across continents.",
          "His writings and speeches—such as those on “Europe’s Net Zero Rebellion” and the “Great Renewable Energy Con”—exposed how well-intentioned policies sometimes were very profitable elites (think Al Gore) while burdening ordinary citizens and undermining national energy security."
        ]
      },
      {
        "title": "Why oil and gas prices could stay high in Europe even if the Iran war ends | Euronews",
        "url": "https://euronews.com/business/2026/04/09/why-oil-and-gas-prices-could-stay-high-in-europe-even-if-the-iran-war-ends",
        "description": "Energy prices in Europe could stay high for a while, even though the region doesn’t rely heavily on the Strait of Hormuz. Here’s what’s behind it.",
        "page_age": "3 days ago",
        "meta_url": {
          "favicon": "https://imgs.search.brave.com/YHwdxHTQIujkueliB2VIksurpENPxI4z7AV-WIQlvZ8/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvMzZkZWEyNzQ1/YjhiMWNmODcyMmRi/MDUwMzM1M2FlZTBk/ODUzNzVkMDc2MWY4/MDEyOWM2YzM4YWQ4/ODVkMzEzMi9ldXJv/bmV3cy5jb20v"
        },
        "thumbnail": {
          "src": "https://imgs.search.brave.com/aARoeI19t6dgWsLEjkpGnI9FfJZooaGUw5hS5nxDwTs/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly9pbWFn/ZXMuZXVyb25ld3Mu/Y29tL2FydGljbGVz/L3N0b3JpZXMvMDkv/NzEvMTIvNTIvMTIw/MHg2NzVfY21zdjJf/MWMwNzVmOWItMjAy/My01OTFlLWE3YmYt/ZjkzYmI0MWEzMDgy/LTk3MTEyNTIuanBn"
        },
        "extra_snippets": [
          "Join us on a journey around Europe to see why protecting ecosystems matters, how our wastewater can be better managed, and to discover some of the best water solutions. Video reports, an animated explainer series and live debate - find out why Water Matters, from Euronews. ... We give you the latest climate facts from the world’s leading source, analyse the trends and explain how our planet is changing.",
          "We meet the experts on the front line of climate change who explore new strategies to mitigate and adapt. ... Be Bold. Discover Saudi ... Gas prices are displayed at a patrol station in Munich, Germany, Saturday, 4 April 2026. - AP Photo/Matthias Schrader ... Despite the major fall in oil prices after the US and Iran confirmed a two-week-long ceasefire, Europe may not yet breathe a sigh of relief due to the long-lasting impact of energy supplies on which the bloc heavily relies.",
          "“Rising gas prices impact British and European energy bills via both the direct cost of gas and the increased cost to generate electricity through gas-fired power plants”, said ICIS UK and European Gas Specialist Ethan Tillcock, who talked to Euronews Business before the ceasefire. Fixed contracts and government support can delay or soften the impact. In Germany, wholesale gas prices linked to TTF influence electricity prices by around 40% and household gas prices by roughly 50–60%, with the rest made up of taxes, network charges and policy costs.",
          "In each episode, two political heavyweights from across the EU face off to propose a diversity of opinions and spark conversations around the most important issues of EU affairs and the wider European political life."
        ]
      },
      {
        "title": "Wired for Security: The EU's Post-2030 Climate Architecture - CleanTechnica",
        "url": "https://cleantechnica.com/2026/04/09/wired-for-security-the-eus-post-2030-climate-architecture",
        "description": "Electrification, Energy Security and the Path to Europe’s 2040 Climate Target. The adoption of the EU’s 2040 climate target marks a turning point in European climate and energy policy. With the headline objective agreed, the central challenge shifts from setting ...",
        "page_age": "2 days ago",
        "meta_url": {
          "favicon": "https://imgs.search.brave.com/ZWmnbtUk1MKRyqzjulj5oZ8uuOmGX_PgmWFavRPkrZc/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvZGNmM2Y1NDcw/MGY0ZDA4ZDk1MDBk/MjIwZWI5NmQ2Y2Uy/ZGE4ZTljNGU0Y2Zh/MTg4MWU2M2JkOTVl/ZmM0NmIyMy9jbGVh/bnRlY2huaWNhLmNv/bS8"
        },
        "thumbnail": {
          "src": "https://imgs.search.brave.com/KHXgmdjEXUDrzjJJ0Ukm77NNe7V2ds51vZ0x4euLaSc/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly9jbGVh/bnRlY2huaWNhLmNv/bS93cC1jb250ZW50/L3VwbG9hZHMvMjAy/NC8wNi9QYXJpcy1C/ZWxnaXVtLU5ldGhl/cmxhbmRzLWdyaWQt/dHJhbnNtaXNzaW9u/LWxpbmVzLWZhcm0t/cG93ZXItZWxlY3Ry/aWNpdHktcmVuZXdh/Ymxlcy1LWUxFLUZJ/RUxELUNsZWFuVGVj/aG5pY2Etd2F0ZXJt/YXJrLmpwZWc"
        },
        "extra_snippets": [
          "Support CleanTechnica's work through a Substack subscription or on Stripe. Electrification, Energy Security and the Path to Europe’s 2040 Climate Target. The adoption of the EU’s 2040 climate target marks a turning point in European climate and energy policy.",
          "Its central argument is that electrification powered by domestically generated renewable energy is not primarily a climate policy but a sovereignty strategy — and that designing the post-2030 legislative package around that insight offers a more robust political and economic foundation than the frameworks that preceded it. The war in the Middle East has once again highlighted European energy insecurity and the consequences of dependence on imported fossil fuels.",
          "See our policy here. ... Transport & Environment’s (T&E) vision is a zero-emission mobility system that is affordable and has minimal impacts on our health, climate and environment. Created over 30 years ago, we have shaped some of Europe’s most important environmental laws.",
          "The post-2030 architecture will fail without a step change in climate investment. Europe faces a significant investment cliff as NextGenerationEU and the Recovery and Resilience Facility wind down, while projections point to an annual investment deficit of €344 billion by 2030 in energy, buildings, transport and clean technology manufacturing alone."
        ]
      },
      {
        "title": "Apply Now: Updating the Carbon Net Zero Roadmap and Strategic Plan in Sri Lanka - fundsforNGOs",
        "url": "https://www2.fundsforngos.org/environment-2/apply-now-updating-the-carbon-net-zero-roadmap-and-strategic-plan-in-sri-lanka/",
        "description": "Deadline: 17-Apr-2026 This UNOPS-managed opportunity provides $117,400 to support Sri Lanka in updating its Carbon Net Zero Roadmap and aligning long-term climate strategies with current NDCs and development priorities. Overview The funding opportunity, managed by UNOPS, supports the Government ...",
        "page_age": "2 days ago",
        "meta_url": {
          "favicon": "https://imgs.search.brave.com/v100HzC6GUqragqnemIeQ2Ro0jrPy8Ow4D8EBMADZM8/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvNzg5MDNiNzAz/YjhmNmYzNWE3ZGIx/YzgyNjNlYTkwMWZl/YzE1NjhjYjllN2Zl/MmMwNmRkZTNmY2Qy/ZmVjNWFlOS93d3cy/LmZ1bmRzZm9ybmdv/cy5vcmcv"
        },
        "thumbnail": {
          "src": "https://imgs.search.brave.com/HGy-rjEMh-jYFxnUduMnyjkw951BIsM3MvkPRUNOYCc/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly9mdW5k/c2Zvcm5nb3NtZWRp/YS5zMy5hbWF6b25h/d3MuY29tL3dwLWNv/bnRlbnQvdXBsb2Fk/cy8yMDIzLzEyLzE5/MTQxMTIwL2ljb24u/cG5n"
        },
        "extra_snippets": [
          "Deadline: 17-Apr-2026 This UNOPS-managed opportunity provides $117,400 to support Sri Lanka in updating its Carbon Net Zero Roadmap and aligning long-term climate strategies with current NDCs and development priorities. Overview The funding opportunity, managed by UNOPS, supports the Government of Sri Lanka in revising its Carbon Net Zero Roadmap and Strategic Plan.",
          "It is particularly valuable for organizations with expertise in climate policy, data systems, and stakeholder engagement.",
          "Technical leadership is provided by UNEP Copenhagen Climate Centre in collaboration with national stakeholders.",
          "UNOPS manages the funding, with technical leadership from UNEP Copenhagen Climate Centre."
        ]
      }
    ]
  },
  {
    "id": "store-example-news-search-3",
    "query": "spacex mars mission",
    "query_translation_key": "app_store_examples.news.search.3",
    "provider": "Brave Search",
    "status": "finished",
    "results": [
      {
        "title": "Artemis II moon mission nears its end. Up next? A moon landing",
        "url": "https://www.usatoday.com/story/news/nation/2026/04/10/nasa-artemis-2-mission-landing-mars/89518025007/",
        "description": "Artemis II is nearing its end, but NASA's moon missions are only just beginning. Here's what next, including that highly-anticipated lunar landing.",
        "page_age": "1 day ago",
        "meta_url": {
          "favicon": "https://imgs.search.brave.com/Y_nf32M16mWMcRGYv2Qt8GUxybiADIXv_NwrMFam-Oc/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvYjRiNmM1Y2E0/MzMwMWQzYTYzNzhk/YjkzZjU0NTRmMDdl/ZWNmMjRiMWIwZjUz/ZDk4M2I5NDlmZjYw/ZTkyNjE4Yy93d3cu/dXNhdG9kYXkuY29t/Lw"
        },
        "thumbnail": {
          "src": "https://imgs.search.brave.com/ppaquBp6Tq9ORQMp1yRzQerX4wmYaixGAdZMufBJNu4/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly93d3cu/Z2FubmV0dC1jZG4u/Y29tL2F1dGhvcmlu/Zy9hdXRob3Jpbmct/aW1hZ2VzLzIwMjYv/MDQvMTAvUEJSRS84/OTU0ODM4MDAwNy1h/cnQtMDAyLWUtMDA5/NTY3LWxhcmdlLmpw/Zz9hdXRvPXdlYnAm/Y3JvcD0xOTE5LDEw/ODAseDAseTAmZm9y/bWF0PXBqcGcmd2lk/dGg9MTIwMA"
        },
        "extra_snippets": [
          "The Artemis III mission will send a new crew of astronauts on the Orion spacecraft to Earth orbit. There, they will dock with at least one of the commercial lunar landers being developed by Elon Musk's SpaceX and Jeff Bezos' Blue Origin.",
          "NASA will also use the mission to test space suits, known as extravehicular activity suits, being developed by Axiom Space for astronauts on the lunar surface. SpaceX, the commercial spaceflight company founded by billionaire Musk, was originally awarded the contract to develop a lunar lander for the first Artemis mission to send astronauts to the surface.",
          "Under that original plan, SpaceX has been working on a configuration of its Starship vehicle, known as the Human Landing System, for human lunar missions.",
          "Here's everything to know about what's next for NASA's first lunar campaign since the Apollo era as the agency works toward a historic moon landing – and eventual human expeditions to Mars. Artemis II: 10 iconic photos from NASA's human moon mission"
        ]
      },
      {
        "title": "Nasa's Artemis II mission was a triumph - but when will astronauts land on the Moon?",
        "url": "https://bbc.com/news/articles/cj0v119zp19o",
        "description": "Nasa's own Office of Inspector ... on 10 March. SpaceX's lunar Starship is at least two years behind its original delivery date, with further delays expected. Blue Origin's Blue Moon is at least eight months late, with nearly half the issues flagged at a 2024 design review still unresolved more than a year later. In pictures: Artemis II crew witness 'Earthset' and a solar eclipse · Artemis II: Inside Nasa's mission to take humans ...",
        "page_age": "1 day ago",
        "meta_url": {
          "favicon": "https://imgs.search.brave.com/kfRy7wuGNQWzU47LzCO0VZPfeuEgMwKe1nZIYNJS9SU/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvODczZDE3NmVj/MzFhZjM1Yzc3YjA0/YTdhM2NkYTkxMGM5/NmQ5Yjc4YTBmMjY2/MTMzNWE1MzgwOWNm/NGQ3YWZlYy9iYmMu/Y29tLw"
        },
        "thumbnail": {
          "src": "https://imgs.search.brave.com/bP2P8d7vdadw-gdF1FY3N6vbaVm8-23AYu9gf90SOM4/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly9pY2hl/Zi5iYmNpLmNvLnVr/L25ld3MvMTAyNC9i/cmFuZGVkX25ld3Mv/Yjc3Ny9saXZlLzMw/MDY0Y2EwLTM0NjAt/MTFmMS1iYzRiLTM5/N2UwOGJlZGU1OS5q/cGc"
        },
        "extra_snippets": [
          "Nasa's own Office of Inspector General laid out the picture starkly in a report published on 10 March. SpaceX's lunar Starship is at least two years behind its original delivery date, with further delays expected. Blue Origin's Blue Moon is at least eight months late, with nearly half the issues flagged at a 2024 design review still unresolved more than a year later. In pictures: Artemis II crew witness 'Earthset' and a solar eclipse · Artemis II: Inside Nasa's mission to take humans back to the Moon",
          "To get boots on the lunar surface, Nasa needs a lander. The US space agency has contracted two private companies to build them: Elon Musk's SpaceX, whose lunar version of its Starship rocket will stand 35 metres tall, and Jeff Bezos's Blue Origin, whose Blue Moon Mark 2 craft is more compact but just as ambitious.",
          "The mission was almost flawless but there are considerable obstacles ahead before a Moon landing.",
          "As I drove around the Kennedy Space Centre after the launch of the Artemis mission, I was struck by the new buildings put up by Blue Origin and others in construction by SpaceX: private sector infrastructure nestling close to a government agency that once sent astronauts to the Moon."
        ]
      },
      {
        "title": "Artemis II astronauts return. What's next for NASA's moon, Mars plans?",
        "url": "https://www.floridatoday.com/story/tech/science/space/2026/04/10/artemis-ii-splashdown-nasa-moon-missions/89555512007/",
        "description": "The Artemis III mission will send a new crew of astronauts on the Orion spacecraft to Earth orbit. There, they will dock with at least one of the commercial lunar landers being developed by Elon Musk's SpaceX and Jeff Bezos' Blue Origin.",
        "page_age": "1 day ago",
        "meta_url": {
          "favicon": "https://imgs.search.brave.com/1rrGGVWqwTsL-hVdLxDbvBdIedj7xNegJC0h2trxUXg/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvMzM1M2QyMTky/YTAzYzY0MjA3MGMw/NTMyZDAwNDEzMzcx/NDMwODIzY2JlYzA0/NTg5NDU4YzY1NGE1/MDg5YmQ2Ny93d3cu/ZmxvcmlkYXRvZGF5/LmNvbS8"
        },
        "thumbnail": {
          "src": "https://imgs.search.brave.com/ppaquBp6Tq9ORQMp1yRzQerX4wmYaixGAdZMufBJNu4/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly93d3cu/Z2FubmV0dC1jZG4u/Y29tL2F1dGhvcmlu/Zy9hdXRob3Jpbmct/aW1hZ2VzLzIwMjYv/MDQvMTAvUEJSRS84/OTU0ODM4MDAwNy1h/cnQtMDAyLWUtMDA5/NTY3LWxhcmdlLmpw/Zz9hdXRvPXdlYnAm/Y3JvcD0xOTE5LDEw/ODAseDAseTAmZm9y/bWF0PXBqcGcmd2lk/dGg9MTIwMA"
        },
        "extra_snippets": [
          "NASA will also use the mission to test space suits, known as extravehicular activity suits, being developed by Axiom Space for astronauts on the lunar surface. SpaceX, the commercial spaceflight company founded by billionaire Musk, was originally awarded the contract to develop a lunar lander for the first Artemis mission to send astronauts to the surface.",
          "Under that original plan, SpaceX has been working on a configuration of its Starship vehicle, known as the Human Landing System, for human lunar missions.",
          "Artemis II astronauts are returning to Earth after a historic moon mission launching from Florida. What's next for NASA's lunar and Mars plans?",
          "Here's everything to know about what's next for NASA's first lunar campaign since the Apollo era as the agency works toward a historic moon landing – and eventual human expeditions to Mars. Artemis II: These 10 photos defined Artemis II moon mission"
        ]
      },
      {
        "title": "How to watch NASA's Artemis II moon mission splashdown off San Diego - Los Angeles Times",
        "url": "https://latimes.com/science/story/2026-04-10/how-to-watch-nasas-artemis-ii-moon-mission-splashdown-off-san-diego",
        "description": "Southern Californians likely won’t be able to see reentry or splashdown in person, but NASA will livestream it. Here’s what you should know.",
        "page_age": "1 day ago",
        "meta_url": {
          "favicon": "https://imgs.search.brave.com/fR0CMvQTmQOlJW7Fv3NJzjh1mJkjyGy6926_gN1Oy3s/rs:fit:32:32:1:0/g:ce/aHR0cDovL2Zhdmlj/b25zLnNlYXJjaC5i/cmF2ZS5jb20vaWNv/bnMvYjQ1YzRlYTM3/ZDcyMjc1Mjc5ZTY3/YWYwNzU0OWVjY2Vm/MDZiYmJkNTM2OGU1/ZWVjYzMxMGRiN2Fm/MDRmMzVlNS9sYXRp/bWVzLmNvbS8"
        },
        "thumbnail": {
          "src": "https://imgs.search.brave.com/KrkCzkucMJamWvgUUFs2dFqvMJ1HrJfPwFuBYyX-7Nc/rs:fit:200:200:1:0/g:ce/aHR0cHM6Ly9jYS10/aW1lcy5icmlnaHRz/cG90Y2RuLmNvbS9k/aW1zNC9kZWZhdWx0/LzQ1ZTRiM2QvMjE0/NzQ4MzY0Ny9zdHJp/cC90cnVlL2Nyb3Av/MjMwNHgxMjEwKzAr/MTYzL3Jlc2l6ZS8x/MjAweDYzMCEvcXVh/bGl0eS83NS8_dXJs/PWh0dHBzJTNBJTJG/JTJGY2FsaWZvcm5p/YS10aW1lcy1icmln/aHRzcG90LnMzLmFt/YXpvbmF3cy5jb20l/MkYyZCUyRjk0JTJG/NjdjNDNiY2Y0Mzhl/YThkZTAwZWE5NDUz/NWZiYiUyRm1lLW9y/aW9uLXNwbGFzaGRv/d24tYXJ0ZW1pcy1u/YXNhLTAxLkpQRUc"
        },
        "extra_snippets": [
          "NASA plans to launch Artemis III, a mission in Earth’s orbit to test docking the Orion spacecraft with SpaceX’s and Blue Origin’s lunar landers, in 2027.",
          "When Glover, still in space, was asked Wednesday evening about the moments from this mission he’ll carry with him for the rest of his life, he joked: “We’ve still got two more days, and riding a fireball through the atmosphere is profound as well.” ... Victor Glover, who grew up in Pomona, will pilot NASA’s first crewed flight to the moon since 1972. If successful, he’ll be the first Black person to reach the moon. March 30, 2026",
          "The Artemis program ultimately aims to land humans back on the moon. NASA eventually hopes to establish a lunar base that will serve as the testing grounds for future missions to Mars.",
          "NASA’s Orion spacecraft for the Artemis I mission was successfully recovered inside the well deck of the USS Portland on Dec."
        ]
      }
    ]
  }
]

export default examples;
