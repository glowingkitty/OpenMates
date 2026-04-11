/**
 * App-store examples for the videos skill.
 *
 * Captured from real YouTube transcript responses, transcript body trimmed to ~3000 chars per video.
 */

export interface VideoTranscriptStoreExample {
  id: string;
  query: string;
  query_translation_key?: string;
  provider?: string;
  status: 'finished';
  results: Array<Record<string, unknown>>;
}

const examples: VideoTranscriptStoreExample[] = [
  {
    "id": "store-example-videos-get-transcript-1",
    "query": "Learning neural networks on YouTube",
    "query_translation_key": "settings.app_store_examples.videos.get_transcript.1",
    "provider": "YouTube Transcript API",
    "status": "finished",
    "url": "https://www.youtube.com/watch?v=aircAruvnKk",
    "results": [
      {
        "type": "transcript_result",
        "url": "https://www.youtube.com/watch?v=aircAruvnKk",
        "transcript": "[00:00:04.219] This is a 3.\n[00:00:06.059] It's sloppily written and rendered at an extremely low resolution of 28x28 pixels,\n[00:00:10.712] but your brain has no trouble recognizing it as a 3.\n[00:00:14.339] And I want you to take a moment to appreciate how\n[00:00:16.559] crazy it is that brains can do this so effortlessly.\n[00:00:19.699] I mean, this, this and this are also recognizable as 3s,\n[00:00:22.961] even though the specific values of each pixel is very different from one\n[00:00:27.213] image to the next.\n[00:00:28.899] The particular light-sensitive cells in your eye that are firing when you\n[00:00:32.948] see this 3 are very different from the ones firing when you see this 3.\n[00:00:37.520] But something in that crazy-smart visual cortex of yours resolves these as representing\n[00:00:42.740] the same idea, while at the same time recognizing other images as their own distinct\n[00:00:47.840] ideas.\n[00:00:49.219] But if I told you, hey, sit down and write for me a program that takes in a grid of\n[00:00:54.634] 28x28 pixels like this and outputs a single number between 0 and 10,\n[00:00:59.134] telling you what it thinks the digit is, well the task goes from comically trivial to\n[00:01:04.745] dauntingly difficult.\n[00:01:07.159] Unless you've been living under a rock, I think I hardly need to motivate the relevance\n[00:01:10.856] and importance of machine learning and neural networks to the present and to the future.\n[00:01:15.120] But what I want to do here is show you what a neural network actually is,\n[00:01:18.950] assuming no background, and to help visualize what it's doing,\n[00:01:22.256] not as a buzzword but as a piece of math.\n[00:01:25.019] My hope is that you come away feeling like the structure itself is motivated,\n[00:01:28.777] and to feel like you know what it means when you read,\n[00:01:31.460] or you hear about a neural network quote-unquote learning.\n[00:01:35.359] This video is just going to be devoted to the structure component of that,\n[00:01:38.260] and the following one is going to tackle learning.\n[00:01:40.959] What we're going to do is put together a neural\n[00:01:43.278] network that can learn to recognize handwritten digits.\n[00:01:49.359] This is a somewhat classic example for introducing the topic,\n[00:01:52.060] and I'm happy to stick with the status quo here,\n[00:01:54.227] because at the end of the two videos I want to point you to a couple good\n[00:01:57.503] resources where you can learn more, and where you can download the code that\n[00:02:00.911] does this and play with it on your own computer.\n[00:02:05.040] There are many many variants of neural networks,\n[00:02:07.661] and in recent years there's been sort of a boom in research towards these variants,\n[00:02:12.246] but in these two introductory videos you and I are just going to look at the simplest\n[00:02:16.942] plain vanilla form with no added frills.\n[00:02:19.860] This is kind of a necessary prerequisite for understanding any of the more pow\n\n[Truncated for preview — full transcript available when you run this skill in a real chat.]",
        "word_count": 3357,
        "characters_count": 18430,
        "language": "English"
      }
    ]
  },
  {
    "id": "store-example-videos-get-transcript-2",
    "query": "Building GPT from scratch tutorial",
    "query_translation_key": "settings.app_store_examples.videos.get_transcript.2",
    "provider": "YouTube Transcript API",
    "status": "finished",
    "url": "https://www.youtube.com/watch?v=kCc8FmEb1nY",
    "results": [
      {
        "type": "transcript_result",
        "url": "https://www.youtube.com/watch?v=kCc8FmEb1nY",
        "transcript": "[00:00:00.199] hi everyone so by now you have probably\n[00:00:02.520] heard of chat GPT it has taken the world\n[00:00:04.919] and AI Community by storm and it is a\n[00:00:07.559] system that allows you to interact with\n[00:00:09.839] an AI and give it text based tasks so\n[00:00:12.839] for example we can ask chat GPT to write\n[00:00:15.080] us a small Hau about how important it is\n[00:00:16.960] that people understand Ai and then they\n[00:00:18.760] can use it to improve the world and make\n[00:00:20.160] it more prosperous so when we run this\n[00:00:23.719] AI knowledge brings prosperity for all\n[00:00:25.640] to see Embrace its\n[00:00:27.399] power okay not bad and so you could see\n[00:00:29.800] that chpt went from left to right and\n[00:00:32.000] generated all these words SE sort of\n[00:00:35.039] sequentially now I asked it already the\n[00:00:37.439] exact same prompt a little bit earlier\n[00:00:39.600] and it generated a slightly different\n[00:00:41.399] outcome ai's power to grow ignorance\n[00:00:44.000] holds us back learn Prosperity weights\n[00:00:47.359] so uh pretty good in both cases and\n[00:00:49.159] slightly different so you can see that\n[00:00:50.759] chat GPT is a probabilistic system and\n[00:00:52.840] for any one prompt it can give us\n[00:00:54.640] multiple answers sort of uh replying to\n[00:00:57.359] it now this is just one example of a\n[00:00:59.759] problem people have come up with many\n[00:01:01.439] many examples and there are entire\n[00:01:03.238] websites that index interactions with\n[00:01:06.000] chpt and so many of them are quite\n[00:01:08.680] humorous explain HTML to me like I'm a\n[00:01:10.959] dog uh write release notes for chess 2\n[00:01:14.560] write a note about Elon Musk buying a\n[00:01:16.400] Twitter and so on so as an example uh\n[00:01:20.560] please write a breaking news article\n[00:01:21.879] about a leaf falling from a\n[00:01:23.478] tree uh and a shocking turn of events a\n[00:01:26.560] leaf has fallen from a tree in the local\n[00:01:28.040] park Witnesses report that the leaf\n[00:01:30.078] which was previously attached to a\n[00:01:31.400] branch of a tree attached itself and\n[00:01:33.438] fell to the ground very dramatic so you\n[00:01:36.280] can see that this is a pretty remarkable\n[00:01:37.959] system and it is what we call a language\n[00:01:40.359] model uh because it um it models the\n[00:01:43.759] sequence of words or characters or\n[00:01:46.399] tokens more generally and it knows how\n[00:01:49.078] sort of words follow each other in\n[00:01:50.680] English language and so from its\n[00:01:52.920] perspective what it is doing is it is\n[00:01:55.519] completing the sequence so I give it the\n[00:01:57.920] start of a sequence and it completes the\n[00:02:00.078] sequence with the outcome and so it's a\n[00:02:02.560] language model in that sense now I would\n[00:02:05.359] like to focus on the under the hood of\n[00:02:07.799] um under the hood components of what\n[00:02:09.878] makes CH GPT work so wh\n\n[Truncated for preview — full transcript available when you run this skill in a real chat.]",
        "word_count": 21030,
        "characters_count": 108990,
        "language": "English (auto-generated)"
      }
    ]
  },
  {
    "id": "store-example-videos-get-transcript-3",
    "query": "Python programming full course",
    "query_translation_key": "settings.app_store_examples.videos.get_transcript.3",
    "provider": "YouTube Transcript API",
    "status": "finished",
    "url": "https://www.youtube.com/watch?v=rfscVS0vtbw",
    "results": [
      {
        "type": "transcript_result",
        "url": "https://www.youtube.com/watch?v=rfscVS0vtbw",
        "transcript": "[00:00:00.000] In this course, I'm going to teach you everything you need to know to get started programming\n[00:00:04.080] in Python. Now, Python is one of the most popular programming languages out there. And it's by far\n[00:00:10.560] one of the most sought after for jobs. And so if you're trying to get a job or you're trying to,\n[00:00:15.759] you know, automate your life, or you're trying to write awesome scripts to do a bunch of different\n[00:00:19.920] things, then Python's for you. Honestly, more and more developers every day are moving their\n[00:00:24.559] projects over to Python because it's such a powerful and it's such an easy to use language. A lot\n[00:00:30.000] of programming languages out there just aren't very beginner friendly. There's a lot of syntax.\n[00:00:34.640] There's a lot of like little things that if you get wrong, the program will yell at you. Python\n[00:00:38.960] is the complete opposite of that. You basically just type out what you want to do and Python does\n[00:00:43.759] it. It's that simple. There's not a whole lot of syntax to learn. The learning curve is literally\n[00:00:49.039] zero. You jump in, you can start writing your first program in seconds. In this course, I'm\n[00:00:54.159] going to teach you guys everything you need to know to get started in Python. I designed this\n[00:00:58.560] course, especially for Python. And each lesson has been specially designed with examples that\n[00:01:03.840] will help you along the way with so many people starting to learn Python. The question isn't,\n[00:01:07.920] why should you learn Python? The question is, why shouldn't you? And I think for a lot of people,\n[00:01:12.560] the reason they might not want to learn Python is because they're intimidated or they're afraid\n[00:01:16.640] that it's going to be too hard. Trust me, I am going to hold your hand through this entire course.\n[00:01:21.200] We're going to talk about all the core concepts in Python. We're going to look at everything you\n[00:01:25.599] need to know to start programming in Python and start being confident and start writing scripts\n[00:01:30.400] and start writing programs that are awesome and doing cool things in your life. Anyway,\n[00:01:34.719] I'm super pumped to be teaching you guys Python. I can't wait to get started in this course. And\n[00:01:38.879] I hope you guys stick around and follow along with the course and learn this amazing programming\n[00:01:43.439] language. In this tutorial, I'm going to show you guys how to install Python onto your computer.\n[00:01:52.480] And we're also going to install a text editor that we can use to write our Python programs in.\n[00:01:58.480] So the first order of business is to actually install Python on your computer. So what we want\n[00:02:04.000] to do is head over to our web browser. And you want to go over here to this page, it's just\n[00:02:09.039] www.python.org forward slash downloads. And on this page, there's going to be two buttons down here.\n[00:0\n\n[Truncated for preview — full transcript available when you run this skill in a real chat.]",
        "word_count": 50862,
        "characters_count": 259401,
        "language": "English"
      }
    ]
  }
]

export default examples;
