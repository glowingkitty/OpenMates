// frontend/packages/ui/src/demo_chats/data/example_chats/beautiful-single-page-html.ts
//
// Example chat: Beautiful Single Page HTML
// Extracted from shared chat 8d8fd415-bef2-4454-b091-4dbddc48f5e3

import type { ExampleChat } from "../../types";

export const beautifulSinglePageHtmlChat: ExampleChat = {
  chat_id: "example-beautiful-single-page-html",
  slug: "beautiful-single-page-html",
  title: "example_chats.beautiful_single_page_html.title",
  summary: "example_chats.beautiful_single_page_html.summary",
  icon: "code",
  category: "software_development",
  keywords: [
    "HTML", "CSS", "single page", "glassmorphism", "animations",
    "web design", "frontend", "template", "responsive design"
  ],
  follow_up_suggestions: [
    "example_chats.beautiful_single_page_html.follow_up_1",
    "example_chats.beautiful_single_page_html.follow_up_2",
    "example_chats.beautiful_single_page_html.follow_up_3",
    "example_chats.beautiful_single_page_html.follow_up_4",
    "example_chats.beautiful_single_page_html.follow_up_5",
    "example_chats.beautiful_single_page_html.follow_up_6",
  ],
  messages: [
    {
      id: "bddc48f5e3-b877148f-cf89-4836-9cca-d84388985b20",
      role: "user",
      content: "example_chats.beautiful_single_page_html.user_message_1",
      created_at: 1775387518,
      category: "software_development",
    },
    {
      id: "0cc48381-d07f-4326-9af9-41b158f3f6b2",
      role: "assistant",
      content: "example_chats.beautiful_single_page_html.assistant_message_2",
      created_at: 1775387523,
      category: "software_development",
      model_name: "Gemini 3 Flash",
    },
  ],
  embeds: [
    {
      embed_id: "994ca928-9170-43ef-90b9-93d7cb00b14d",
      type: "code",
      content: `type: code
app_id: code
skill_id: code
language: html
code: "<!DOCTYPE html>\\n<html lang=\\"en\\">\\n<head>\\n    <meta charset=\\"UTF-8\\">\\n    <meta name=\\"viewport\\" content=\\"width=device-width, initial-scale=1.0\\">\\n    <title>Modern Aurora Landing</title>\\n    <style>\\n        :root {\\n            --primary: #6366f1;\\n            --secondary: #a855f7;\\n            --bg-dark: #0f172a;\\n            --glass: rgba(255, 255, 255, 0.05);\\n            --glass-border: rgba(255, 255, 255, 0.1);\\n        }\\n\\n        * {\\n            margin: 0;\\n            padding: 0;\\n            box-sizing: border-box;\\n            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;\\n        }\\n\\n        body {\\n            background-color: var(--bg-dark);\\n            color: white;\\n            overflow: hidden; /* Prevents scrollbars during background animations */\\n            height: 100vh;\\n            display: flex;\\n            justify-content: center;\\n            align-items: center;\\n        }\\n\\n        /* Animated Gradient Background */\\n        .background-canvas {\\n            position: fixed;\\n            top: 0;\\n            left: 0;\\n            width: 100%;\\n            height: 100%;\\n            z-index: -1;\\n            background: linear-gradient(125deg, #0f172a 0%, #1e1b4b 50%, #312e81 100%);\\n            background-size: 400% 400%;\\n            animation: gradientBG 15s ease infinite;\\n        }\\n\\n        @keyframes gradientBG {\\n            0% { background-position: 0% 50%; }\\n            50% { background-position: 100% 50%; }\\n            100% { background-position: 0% 50%; }\\n        }\\n\\n        /* Floating Blobs */\\n        .blob {\\n            position: absolute;\\n            width: 300px;\\n            height: 300px;\\n            background: linear-gradient(to right, var(--primary), var(--secondary));\\n            filter: blur(80px);\\n            border-radius: 50%;\\n            opacity: 0.4;\\n            z-index: -1;\\n            animation: float 20s infinite alternate;\\n        }\\n\\n        .blob-1 { top: -100px; left: -100px; }\\n        .blob-2 { bottom: -100px; right: -100px; animation-delay: -5s; }\\n\\n        @keyframes float {\\n            0% { transform: translate(0, 0) scale(1); }\\n            33% { transform: translate(10vw, 20vh) scale(1.2); }\\n            66% { transform: translate(-5vw, 15vh) scale(0.8); }\\n            100% { transform: translate(0, 0) scale(1); }\\n        }\\n\\n        /* Main Card */\\n        .glass-card {\\n            background: var(--glass);\\n            backdrop-filter: blur(12px);\\n            -webkit-backdrop-filter: blur(12px);\\n            border: 1px solid var(--glass-border);\\n            border-radius: 24px;\\n            padding: 3rem;\\n            text-align: center;\\n            max-width: 500px;\\n            width: 90%;\\n            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);\\n            animation: fadeInUp 1s ease-out forwards;\\n            opacity: 0;\\n        }\\n\\n        @keyframes fadeInUp {\\n            from {\\n                opacity: 0;\\n                transform: translateY(30px);\\n            }\\n            to {\\n                opacity: 1;\\n                transform: translateY(0);\\n            }\\n        }\\n\\n        h1 {\\n            font-size: 2.5rem;\\n            margin-bottom: 1rem;\\n            background: linear-gradient(to right, #fff, #94a3b8);\\n            -webkit-background-clip: text;\\n            -webkit-text-fill-color: transparent;\\n        }\\n\\n        p {\\n            color: #94a3b8;\\n            line-height: 1.6;\\n            margin-bottom: 2rem;\\n        }\\n\\n        /* CTA Button Animation */\\n        .btn {\\n            display: inline-block;\\n            padding: 12px 32px;\\n            background: white;\\n            color: var(--bg-dark);\\n            text-decoration: none;\\n            font-weight: 600;\\n            border-radius: 12px;\\n            transition: all 0.3s ease;\\n            position: relative;\\n            overflow: hidden;\\n        }\\n\\n        .btn:hover {\\n            transform: translateY(-2px);\\n            box-shadow: 0 0 20px rgba(99, 102, 241, 0.6);\\n        }\\n\\n        .btn:active {\\n            transform: translateY(0);\\n        }\\n\\n        /* Subtle pulse for the button */\\n        .pulse {\\n            animation: pulse-border 2s infinite;\\n        }\\n\\n        @keyframes pulse-border {\\n            0% { box-shadow: 0 0 0 0 rgba(255, 255, 255, 0.4); }\\n            70% { box-shadow: 0 0 0 15px rgba(255, 255, 255, 0); }\\n            100% { box-shadow: 0 0 0 0 rgba(255, 255, 255, 0); }\\n        }\\n    </style>\\n</head>\\n<body>\\n\\n    <div class=\\"background-canvas\\"></div>\\n    <div class=\\"blob blob-1\\"></div>\\n    <div class=\\"blob blob-2\\"></div>\\n\\n    <main class=\\"glass-card\\">\\n        <h1>Experience Flow</h1>\\n        <p>A beautiful intersection of design and motion. This interface uses pure CSS animations and glassmorphism to create a tactile digital experience.</p>\\n        <a href=\\"#\\" class=\\"btn pulse\\">Get Started</a>\\n    </main>\\n\\n</body>\\n</html>\\n"
filename: index.html
status: finished
line_count: 165`,
      parent_embed_id: null,
      embed_ids: null,
    },
  ],
  metadata: {
    featured: true,
    order: 3,
  },
};