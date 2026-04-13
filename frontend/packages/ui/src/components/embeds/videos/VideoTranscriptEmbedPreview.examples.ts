/**
 * App-store examples for the videos skill.
 *
 * Captured from real YouTube transcripts on non-technical talks (commencement speech, TED talks). Transcript bodies trimmed to ~3000 chars.
 */

export interface VideoTranscriptStoreExample {
  id: string;
  query: string;
  query_translation_key?: string;
  provider?: string;
  status: 'finished';
  results: Array<Record<string, unknown>>;
  url?: string;
}

const examples: VideoTranscriptStoreExample[] = [
  {
    "id": "store-example-videos-get-transcript-1",
    "query": "A famous life-advice speech",
    "query_translation_key": "settings.app_store_examples.videos.get_transcript.1",
    "provider": "YouTube",
    "status": "finished",
    "url": "https://www.youtube.com/watch?v=UF8uR6Z6KLc",
    "results": [
      {
        "type": "transcript_result",
        "url": "https://www.youtube.com/watch?v=UF8uR6Z6KLc",
        "transcript": "[00:00:07.469] This program is brought to you by Stanford University.\n[00:00:10.470] Please visit us at stanford.edu\n[00:00:22.492] Thank You. I am honored to be with you today at your commencement\n[00:00:30.019] from one of the finest universities in the world.\n[00:00:35.558] Truth be told I never graduated from college\n[00:00:41.560] and this is the closest I've ever gotten to a college graduation.\n[00:00:47.979] Today I want to tell you three stories from my life. That's it.\n[00:00:52.009] No big deal. Just three stories.\n[00:00:55.850] The first story is about connecting the dots.\n[00:01:01.009] I dropped out of Reed College after the first 6 months,\n[00:01:03.979] but then stayed around as a drop-in\n[00:01:05.799] for another 18 months or so before I really quit.\n[00:01:09.409] So why did I drop out?\n[00:01:12.230] It started before I was born.\n[00:01:15.250] My biological mother was a young, unwed graduate student,\n[00:01:19.239] and she decided to put me up for adoption.\n[00:01:22.359] She felt very strongly that I should be adopted by college graduates,\n[00:01:26.308] so everything was all set for me to\n[00:01:28.608] be adopted at birth by a lawyer and his wife.\n[00:01:31.739] Except that when I popped out they decided\n[00:01:34.150] at the last minute that they really wanted a girl.\n[00:01:37.920] So my parents, who were on a waiting list,\n[00:01:40.159] got a call in the middle of the night asking: \"We have an unexpected\n[00:01:44.469] baby boy; do you want him?\"\n[00:01:47.430] They said: \"Of course.\" My biological mother later found out that\n[00:01:53.299] my mother had never graduated from college\n[00:01:55.310] and that my father had never graduated from high school.\n[00:01:59.159] She refused to sign the final adoption papers.\n[00:02:03.430] She only relented a few months later when\n[00:02:05.390] my parents promised that I would go to college. This was the start in my life.\n[00:02:12.539] And 17 years later I did go to college. But I naively chose a college\n[00:02:19.340] that was almost as expensive as Stanford,\n[00:02:22.469] and all of my working-class parents'\n[00:02:24.310] savings were being spent on my college tuition.\n[00:02:27.610] After six months, I couldn't see the value in it.\n[00:02:30.719] I had no idea what I wanted to do with my life\n[00:02:32.759] and no idea how college was going to help me figure it out.\n[00:02:36.849] And here I was spending all of the money my parents had saved\n[00:02:40.288] their entire life.\n[00:02:42.599] So I decided to drop out and trust that it would all work out OK.\n[00:02:46.938] It was pretty scary at the time,\n[00:02:49.399] but looking back it was one of the best decisions I ever made.\n[00:02:54.080] The minute I dropped out I could stop\n[00:02:56.689] taking the required classes that didn't interest me,\n[00:02:59.740] and begin dropping in on the ones that looked interesting.\n[00:03:04.759] It wasn't all romantic. I didn't have a dorm room,\n[00:03:08.169] so I slept on the floor \n\n[Truncated for preview — full transcript available when you run this skill in a real chat.]",
        "word_count": 2298,
        "characters_count": 12131,
        "language": "English - English"
      }
    ]
  },
  {
    "id": "store-example-videos-get-transcript-2",
    "query": "A popular TED talk on body language",
    "query_translation_key": "settings.app_store_examples.videos.get_transcript.2",
    "provider": "YouTube",
    "status": "finished",
    "url": "https://www.youtube.com/watch?v=Ks-_Mh1QhMc",
    "results": [
      {
        "type": "transcript_result",
        "url": "https://www.youtube.com/watch?v=Ks-_Mh1QhMc",
        "transcript": "[00:00:00.000] Translator: Joseph Geni Reviewer: Morton Bast\n[00:00:15.967] So I want to start by offering you a free no-tech life hack,\n[00:00:21.388] and all it requires of you is this:\n[00:00:24.010] that you change your posture for two minutes.\n[00:00:28.196] But before I give it away, I want to ask you to right now\n[00:00:31.620] do a little audit of your body and what you're doing with your body.\n[00:00:35.213] So how many of you are sort of making yourselves smaller?\n[00:00:37.929] Maybe you're hunching, crossing your legs, maybe wrapping your ankles.\n[00:00:41.274] Sometimes we hold onto our arms like this.\n[00:00:45.012] Sometimes we spread out. (Laughter)\n[00:00:48.683] I see you.\n[00:00:50.956] So I want you to pay attention to what you're doing right now.\n[00:00:53.970] We're going to come back to that in a few minutes,\n[00:00:56.329] and I'm hoping that if you learn to tweak this a little bit,\n[00:00:59.277] it could significantly change the way your life unfolds.\n[00:01:02.713] So, we're really fascinated with body language,\n[00:01:07.236] and we're particularly interested in other people's body language.\n[00:01:11.159] You know, we're interested in, like, you know — (Laughter) —\n[00:01:15.381] an awkward interaction, or a smile,\n[00:01:19.778] or a contemptuous glance, or maybe a very awkward wink,\n[00:01:24.010] or maybe even something like a handshake.\n[00:01:27.248] Narrator: Here they are arriving at Number 10.\n[00:01:30.597] This lucky policeman gets to shake hands with the President of the United States.\n[00:01:35.090] Here comes the Prime Minister -- No. (Laughter) (Applause)\n[00:01:40.018] (Laughter) (Applause)\n[00:01:42.692] Amy Cuddy: So a handshake, or the lack of a handshake,\n[00:01:46.400] can have us talking for weeks and weeks and weeks.\n[00:01:48.924] Even the BBC and The New York Times.\n[00:01:51.063] So obviously when we think about nonverbal behavior,\n[00:01:55.015] or body language -- but we call it nonverbals as social scientists --\n[00:01:58.403] it's language, so we think about communication.\n[00:02:01.283] When we think about communication, we think about interactions.\n[00:02:04.310] So what is your body language communicating to me?\n[00:02:06.748] What's mine communicating to you?\n[00:02:08.814] And there's a lot of reason to believe that this is a valid way to look at this.\n[00:02:14.787] So social scientists have spent a lot of time\n[00:02:17.055] looking at the effects of our body language,\n[00:02:19.159] or other people's body language, on judgments.\n[00:02:21.468] And we make sweeping judgments and inferences from body language.\n[00:02:24.907] And those judgments can predict really meaningful life outcomes\n[00:02:28.897] like who we hire or promote, who we ask out on a date.\n[00:02:32.691] For example, Nalini Ambady, a researcher at Tufts University,\n[00:02:37.376] shows that when people watch 30-second soundless clips\n[00:02:41.848] of real physician-patient interactions,\n[00:02:44.872] their judgment\n\n[Truncated for preview — full transcript available when you run this skill in a real chat.]",
        "word_count": 3647,
        "characters_count": 20100,
        "language": "English"
      }
    ]
  },
  {
    "id": "store-example-videos-get-transcript-3",
    "query": "A popular TED talk on connection",
    "query_translation_key": "settings.app_store_examples.videos.get_transcript.3",
    "provider": "YouTube",
    "status": "finished",
    "url": "https://www.youtube.com/watch?v=iCvmsMzlF7o",
    "results": [
      {
        "type": "transcript_result",
        "url": "https://www.youtube.com/watch?v=iCvmsMzlF7o",
        "transcript": "[00:00:16.859] So, I'll start with this: a couple years ago, an event planner called me\n[00:00:20.344] because I was going to do a speaking event.\n[00:00:22.417] And she called, and she said,\n[00:00:24.132] \"I'm really struggling with how to write about you on the little flyer.\"\n[00:00:27.728] And I thought, \"Well, what's the struggle?\"\n[00:00:30.487] And she said, \"Well, I saw you speak,\n[00:00:32.415] and I'm going to call you a researcher, I think,\n[00:00:34.924] but I'm afraid if I call you a researcher, no one will come,\n[00:00:37.837] because they'll think you're boring and irrelevant.\"\n[00:00:40.320] (Laughter)\n[00:00:41.344] And I was like, \"Okay.\"\n[00:00:42.945] And she said, \"But the thing I liked about your talk\n[00:00:45.447] is you're a storyteller.\n[00:00:46.686] So I think what I'll do is just call you a storyteller.\"\n[00:00:49.990] And of course, the academic, insecure part of me\n[00:00:52.990] was like, \"You're going to call me a what?\"\n[00:00:55.323] And she said, \"I'm going to call you a storyteller.\"\n[00:00:57.896] And I was like, \"Why not 'magic pixie'?\"\n[00:01:00.768] (Laughter)\n[00:01:03.648] I was like, \"Let me think about this for a second.\"\n[00:01:07.290] I tried to call deep on my courage.\n[00:01:09.853] And I thought, you know, I am a storyteller.\n[00:01:12.989] I'm a qualitative researcher.\n[00:01:14.418] I collect stories; that's what I do.\n[00:01:16.656] And maybe stories are just data with a soul.\n[00:01:19.584] And maybe I'm just a storyteller.\n[00:01:21.989] And so I said, \"You know what?\n[00:01:23.673] Why don't you just say I'm a researcher-storyteller.\"\n[00:01:26.337] And she went, \"Ha ha. There's no such thing.\"\n[00:01:29.989] (Laughter)\n[00:01:31.697] So I'm a researcher-storyteller, and I'm going to talk to you today --\n[00:01:35.697] we're talking about expanding perception --\n[00:01:37.771] and so I want to talk to you and tell some stories\n[00:01:40.177] about a piece of my research that fundamentally expanded my perception\n[00:01:45.359] and really actually changed the way that I live and love\n[00:01:48.272] and work and parent.\n[00:01:50.093] And this is where my story starts.\n[00:01:52.989] When I was a young researcher, doctoral student,\n[00:01:55.697] my first year, I had a research professor who said to us,\n[00:01:59.697] \"Here's the thing, if you cannot measure it, it does not exist.\"\n[00:02:05.373] And I thought he was just sweet-talking me.\n[00:02:08.338] I was like, \"Really?\" and he was like, \"Absolutely.\"\n[00:02:10.800] And so you have to understand\n[00:02:13.076] that I have a bachelor's and a master's in social work,\n[00:02:15.681] and I was getting my Ph.D. in social work, so my entire academic career\n[00:02:19.079] was surrounded by people who kind of believed in the \"life's messy, love it.\"\n[00:02:25.473] And I'm more of the, \"life's messy, clean it up, organize it\n[00:02:30.925] and put it into a bento box.\"\n[00:02:32.727] (Laughter)\n[00:02:35.020] And so to think that I had found my way\n\n[Truncated for preview — full transcript available when you run this skill in a real chat.]",
        "word_count": 3111,
        "characters_count": 16923,
        "language": "English"
      }
    ]
  }
]

export default examples;
