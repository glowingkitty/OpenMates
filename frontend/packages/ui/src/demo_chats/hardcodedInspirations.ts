// frontend/packages/ui/src/demo_chats/hardcodedInspirations.ts
//
// Hardcoded daily inspirations shown instantly on page load, before any async
// data (IndexedDB / server defaults) is available. These ensure the banner is
// always visible from the very first frame.
//
// Each inspiration has its text fields (phrase, title, assistant_response,
// follow_up_suggestions) translated into all 21 supported languages. Video
// metadata is language-independent and shared across locales.
//
// Once real inspirations arrive (from IndexedDB, server, or WebSocket), they
// replace these hardcoded ones with a fade transition.

import type { DailyInspiration } from "../stores/dailyInspirationStore";

// ─── Shared video metadata (language-independent) ────────────────────────────

const VIDEOS = {
  dreams: {
    youtube_id: "XK4yjmApcHo",
    title: "The Strange Science of Why We Dream",
    thumbnail_url: "https://i.ytimg.com/vi/XK4yjmApcHo/hqdefault.jpg",
    channel_name: "Be Smart",
    view_count: 4397676,
    duration_seconds: 902,
    published_at: "2021-12-22T16:36:19Z",
  },
  eniac: {
    youtube_id: "Zevt2blQyVs",
    title: "The Secret History of The ENIAC Women | Kathy Kleiman | TEDxBeaconStreet",
    thumbnail_url: "https://i.ytimg.com/vi/Zevt2blQyVs/hqdefault.jpg",
    channel_name: "TEDx Talks",
    view_count: 22888,
    duration_seconds: 823,
    published_at: "2018-02-16T19:54:20Z",
  },
  urban_farms: {
    youtube_id: "G88JZ1DIdg8",
    title: "How urban agriculture is transforming Detroit | Devita Davison",
    thumbnail_url: "https://i.ytimg.com/vi/G88JZ1DIdg8/hqdefault.jpg",
    channel_name: "TED",
    view_count: 108327,
    duration_seconds: 743,
    published_at: "2018-01-09T16:14:15Z",
  },
} as const;

// ─── Translation type ────────────────────────────────────────────────────────

interface InspirationText {
  phrase: string;
  title: string;
  assistant_response: string;
  follow_up_suggestions: [string, string, string];
}

// ─── Translations per inspiration ────────────────────────────────────────────

const DREAMS_TEXT: Record<string, InspirationText> = {
  en: {
    phrase: "Why does your brain create entire worlds while you sleep?",
    title: "The neuroscience of dreaming",
    assistant_response: "Every night your brain enters a strange world of its own making. Scientists still debate why — from memory consolidation to emotional processing, the theories are fascinating and sometimes contradictory. This video from Be Smart dives into the latest neuroscience research on dreaming, exploring what happens in your brain during REM sleep and why it might matter more than you think. Let's explore the science behind your nightly adventures.",
    follow_up_suggestions: ["What happens during REM sleep?", "Can we control our dreams?", "Why do some people never remember dreams?"],
  },
  de: {
    phrase: "Warum erschafft dein Gehirn ganze Welten, während du schläfst?",
    title: "Die Neurowissenschaft des Träumens",
    assistant_response: "Jede Nacht betritt dein Gehirn eine seltsame Welt eigener Schöpfung. Wissenschaftler debattieren noch immer darüber — von Gedächtniskonsolidierung bis emotionaler Verarbeitung, die Theorien sind faszinierend und manchmal widersprüchlich. Dieses Video von Be Smart taucht in die neueste neurowissenschaftliche Forschung zum Träumen ein und erforscht, was während des REM-Schlafs in deinem Gehirn passiert und warum es wichtiger sein könnte als du denkst. Lass uns die Wissenschaft hinter deinen nächtlichen Abenteuern erkunden.",
    follow_up_suggestions: ["Was passiert während des REM-Schlafs?", "Können wir unsere Träume kontrollieren?", "Warum erinnern sich manche Menschen nie an Träume?"],
  },
  zh: {
    phrase: "为什么你的大脑会在你睡觉时创造整个世界？",
    title: "梦的神经科学",
    assistant_response: "每晚你的大脑都会进入一个自己创造的奇异世界。科学家们仍在争论原因——从记忆巩固到情绪处理，这些理论既迷人又有时相互矛盾。Be Smart的这个视频深入探讨了关于做梦的最新神经科学研究，探索了REM睡眠期间大脑中发生的事情以及为什么它可能比你想象的更重要。让我们一起探索夜间冒险背后的科学。",
    follow_up_suggestions: ["REM睡眠期间会发生什么？", "我们能控制自己的梦吗？", "为什么有些人从不记得自己的梦？"],
  },
  es: {
    phrase: "¿Por qué tu cerebro crea mundos enteros mientras duermes?",
    title: "La neurociencia de los sueños",
    assistant_response: "Cada noche tu cerebro entra en un mundo extraño de su propia creación. Los científicos aún debaten por qué — desde la consolidación de la memoria hasta el procesamiento emocional, las teorías son fascinantes y a veces contradictorias. Este video de Be Smart explora la última investigación neurocientífica sobre los sueños, descubriendo qué sucede en tu cerebro durante el sueño REM y por qué podría importar más de lo que piensas. Exploremos la ciencia detrás de tus aventuras nocturnas.",
    follow_up_suggestions: ["¿Qué sucede durante el sueño REM?", "¿Podemos controlar nuestros sueños?", "¿Por qué algunas personas nunca recuerdan sus sueños?"],
  },
  fr: {
    phrase: "Pourquoi votre cerveau crée-t-il des mondes entiers pendant que vous dormez ?",
    title: "Les neurosciences du rêve",
    assistant_response: "Chaque nuit, votre cerveau entre dans un monde étrange de sa propre création. Les scientifiques débattent encore — de la consolidation de la mémoire au traitement émotionnel, les théories sont fascinantes et parfois contradictoires. Cette vidéo de Be Smart plonge dans les dernières recherches en neurosciences sur le rêve, explorant ce qui se passe dans votre cerveau pendant le sommeil paradoxal et pourquoi cela pourrait être plus important que vous ne le pensez. Explorons la science derrière vos aventures nocturnes.",
    follow_up_suggestions: ["Que se passe-t-il pendant le sommeil paradoxal ?", "Peut-on contrôler nos rêves ?", "Pourquoi certaines personnes ne se souviennent jamais de leurs rêves ?"],
  },
  pt: {
    phrase: "Por que seu cérebro cria mundos inteiros enquanto você dorme?",
    title: "A neurociência dos sonhos",
    assistant_response: "Toda noite seu cérebro entra em um mundo estranho de sua própria criação. Cientistas ainda debatem por quê — da consolidação da memória ao processamento emocional, as teorias são fascinantes e às vezes contraditórias. Este vídeo do Be Smart mergulha nas últimas pesquisas neurocientíficas sobre sonhos, explorando o que acontece no seu cérebro durante o sono REM e por que isso pode importar mais do que você pensa. Vamos explorar a ciência por trás de suas aventuras noturnas.",
    follow_up_suggestions: ["O que acontece durante o sono REM?", "Podemos controlar nossos sonhos?", "Por que algumas pessoas nunca lembram dos sonhos?"],
  },
  ru: {
    phrase: "Почему ваш мозг создаёт целые миры, пока вы спите?",
    title: "Нейронаука сновидений",
    assistant_response: "Каждую ночь ваш мозг попадает в странный мир собственного творения. Учёные всё ещё спорят почему — от консолидации памяти до эмоциональной обработки, теории увлекательны и иногда противоречивы. Это видео от Be Smart погружается в новейшие нейронаучные исследования сновидений, исследуя, что происходит в вашем мозге во время быстрого сна и почему это может быть важнее, чем вы думаете. Давайте исследуем науку, стоящую за вашими ночными приключениями.",
    follow_up_suggestions: ["Что происходит во время быстрого сна?", "Можем ли мы контролировать свои сны?", "Почему некоторые люди никогда не помнят снов?"],
  },
  ja: {
    phrase: "なぜ脳は眠っている間に世界を作り出すのでしょうか？",
    title: "夢の神経科学",
    assistant_response: "毎晩、あなたの脳は独自の不思議な世界に入ります。科学者たちはまだその理由を議論しています — 記憶の定着から感情の処理まで、理論は魅力的で時に矛盾しています。Be Smartのこの動画は、夢に関する最新の神経科学研究に深く踏み込み、レム睡眠中に脳で何が起きているのか、そしてそれがあなたが思っている以上に重要かもしれない理由を探ります。夜の冒険の背後にある科学を探りましょう。",
    follow_up_suggestions: ["レム睡眠中に何が起きる？", "夢をコントロールできる？", "なぜ夢を覚えていない人がいるの？"],
  },
  ko: {
    phrase: "왜 뇌는 잠자는 동안 완전한 세계를 만들어낼까요?",
    title: "꿈의 신경과학",
    assistant_response: "매일 밤 여러분의 뇌는 스스로 만든 이상한 세계로 들어갑니다. 과학자들은 여전히 그 이유에 대해 논쟁 중입니다 — 기억 통합부터 감정 처리까지, 이론들은 매력적이고 때로는 모순적입니다. Be Smart의 이 영상은 꿈에 관한 최신 신경과학 연구를 깊이 탐구하며, REM 수면 동안 뇌에서 일어나는 일과 그것이 생각보다 더 중요할 수 있는 이유를 알아봅니다. 밤마다 펼쳐지는 모험 뒤의 과학을 탐험해봅시다.",
    follow_up_suggestions: ["REM 수면 동안 무슨 일이 일어나나요?", "꿈을 조절할 수 있나요?", "왜 어떤 사람들은 꿈을 기억하지 못하나요?"],
  },
  it: {
    phrase: "Perché il tuo cervello crea mondi interi mentre dormi?",
    title: "Le neuroscienze del sogno",
    assistant_response: "Ogni notte il tuo cervello entra in uno strano mondo di sua creazione. Gli scienziati dibattono ancora sul perché — dal consolidamento della memoria all'elaborazione emotiva, le teorie sono affascinanti e talvolta contraddittorie. Questo video di Be Smart approfondisce le ultime ricerche neuroscientifiche sui sogni, esplorando cosa succede nel tuo cervello durante il sonno REM e perché potrebbe essere più importante di quanto pensi. Esploriamo la scienza dietro le tue avventure notturne.",
    follow_up_suggestions: ["Cosa succede durante il sonno REM?", "Possiamo controllare i nostri sogni?", "Perché alcune persone non ricordano mai i sogni?"],
  },
  tr: {
    phrase: "Beyin uyurken neden koskoca dünyalar yaratır?",
    title: "Rüyanın nörobilimi",
    assistant_response: "Her gece beyniniz kendi yarattığı garip bir dünyaya girer. Bilim insanları hâlâ nedenini tartışıyor — hafıza pekiştirmeden duygusal işlemeye, teoriler büyüleyici ve bazen çelişkili. Be Smart'ın bu videosu rüya görme üzerine en son nörobilim araştırmalarına dalarak REM uykusu sırasında beyninizde neler olduğunu ve bunun düşündüğünüzden daha önemli olabileceğini araştırıyor. Gece maceralarınızın arkasındaki bilimi keşfedelim.",
    follow_up_suggestions: ["REM uykusu sırasında ne olur?", "Rüyalarımızı kontrol edebilir miyiz?", "Neden bazı insanlar rüyalarını hiç hatırlamaz?"],
  },
  vi: {
    phrase: "Tại sao não bộ lại tạo ra cả thế giới khi bạn ngủ?",
    title: "Khoa học thần kinh về giấc mơ",
    assistant_response: "Mỗi đêm, não bạn bước vào một thế giới kỳ lạ do chính nó tạo ra. Các nhà khoa học vẫn đang tranh luận tại sao — từ củng cố trí nhớ đến xử lý cảm xúc, các lý thuyết rất hấp dẫn và đôi khi mâu thuẫn. Video này từ Be Smart đi sâu vào nghiên cứu khoa học thần kinh mới nhất về giấc mơ, khám phá những gì xảy ra trong não bạn khi ngủ REM và tại sao nó có thể quan trọng hơn bạn nghĩ. Hãy cùng khám phá khoa học đằng sau những cuộc phiêu lưu ban đêm của bạn.",
    follow_up_suggestions: ["Điều gì xảy ra trong giấc ngủ REM?", "Chúng ta có thể kiểm soát giấc mơ không?", "Tại sao một số người không bao giờ nhớ giấc mơ?"],
  },
  id: {
    phrase: "Mengapa otak menciptakan seluruh dunia saat Anda tidur?",
    title: "Ilmu saraf tentang mimpi",
    assistant_response: "Setiap malam otak Anda memasuki dunia aneh ciptaannya sendiri. Para ilmuwan masih memperdebatkan alasannya — dari konsolidasi memori hingga pemrosesan emosi, teori-teorinya menarik dan terkadang kontradiktif. Video dari Be Smart ini mendalami penelitian ilmu saraf terbaru tentang mimpi, mengeksplorasi apa yang terjadi di otak Anda selama tidur REM dan mengapa hal itu mungkin lebih penting dari yang Anda kira. Mari jelajahi sains di balik petualangan malam Anda.",
    follow_up_suggestions: ["Apa yang terjadi selama tidur REM?", "Bisakah kita mengendalikan mimpi?", "Mengapa sebagian orang tidak pernah ingat mimpi?"],
  },
  pl: {
    phrase: "Dlaczego twój mózg tworzy całe światy podczas snu?",
    title: "Neuronauka snów",
    assistant_response: "Każdej nocy twój mózg wchodzi w dziwny świat własnego stworzenia. Naukowcy wciąż debatują dlaczego — od konsolidacji pamięci po przetwarzanie emocji, teorie są fascynujące i czasem sprzeczne. Ten film od Be Smart zagłębia się w najnowsze badania neuronaukowe nad snami, badając co dzieje się w mózgu podczas snu REM i dlaczego może to mieć większe znaczenie niż myślisz. Odkryjmy naukę kryjącą się za twoimi nocnymi przygodami.",
    follow_up_suggestions: ["Co dzieje się podczas snu REM?", "Czy możemy kontrolować nasze sny?", "Dlaczego niektórzy ludzie nigdy nie pamiętają snów?"],
  },
  nl: {
    phrase: "Waarom creëert je brein hele werelden terwijl je slaapt?",
    title: "De neurowetenschap van dromen",
    assistant_response: "Elke nacht betreedt je brein een vreemde wereld van eigen makelij. Wetenschappers debatteren nog steeds waarom — van geheugenconsolidatie tot emotionele verwerking, de theorieën zijn fascinerend en soms tegenstrijdig. Deze video van Be Smart duikt in het nieuwste neurowetenschappelijke onderzoek naar dromen en verkent wat er tijdens de REM-slaap in je brein gebeurt en waarom het belangrijker zou kunnen zijn dan je denkt. Laten we de wetenschap achter je nachtelijke avonturen ontdekken.",
    follow_up_suggestions: ["Wat gebeurt er tijdens de REM-slaap?", "Kunnen we onze dromen controleren?", "Waarom herinneren sommige mensen zich nooit hun dromen?"],
  },
  ar: {
    phrase: "لماذا يخلق دماغك عوالم كاملة أثناء نومك؟",
    title: "علم الأعصاب وراء الأحلام",
    assistant_response: "كل ليلة يدخل دماغك عالماً غريباً من صنعه. لا يزال العلماء يتناقشون حول السبب — من تعزيز الذاكرة إلى المعالجة العاطفية، النظريات رائعة ومتناقضة أحياناً. يغوص هذا الفيديو من Be Smart في أحدث أبحاث علم الأعصاب حول الأحلام، مستكشفاً ما يحدث في دماغك أثناء نوم حركة العين السريعة ولماذا قد يكون أهم مما تعتقد. دعنا نستكشف العلم وراء مغامراتك الليلية.",
    follow_up_suggestions: ["ماذا يحدث أثناء نوم حركة العين السريعة؟", "هل يمكننا التحكم في أحلامنا؟", "لماذا لا يتذكر بعض الناس أحلامهم أبداً؟"],
  },
  hi: {
    phrase: "नींद में आपका दिमाग पूरी दुनिया क्यों बनाता है?",
    title: "सपनों का तंत्रिका विज्ञान",
    assistant_response: "हर रात आपका दिमाग अपनी बनाई एक अजीब दुनिया में प्रवेश करता है। वैज्ञानिक अभी भी बहस कर रहे हैं क्यों — स्मृति समेकन से भावनात्मक प्रसंस्करण तक, सिद्धांत आकर्षक और कभी-कभी विरोधाभासी हैं। Be Smart का यह वीडियो सपनों पर नवीनतम तंत्रिका विज्ञान अनुसंधान में गहराई से उतरता है, REM नींद के दौरान आपके मस्तिष्क में क्या होता है और यह आपकी सोच से अधिक महत्वपूर्ण क्यों हो सकता है, इसकी खोज करता है। आइए अपने रात के रोमांच के पीछे के विज्ञान का पता लगाएं।",
    follow_up_suggestions: ["REM नींद के दौरान क्या होता है?", "क्या हम अपने सपनों को नियंत्रित कर सकते हैं?", "कुछ लोग सपने क्यों नहीं याद रख पाते?"],
  },
  th: {
    phrase: "ทำไมสมองถึงสร้างโลกทั้งใบขณะที่คุณหลับ?",
    title: "ประสาทวิทยาของการฝัน",
    assistant_response: "ทุกคืนสมองของคุณเข้าสู่โลกแปลกประหลาดที่มันสร้างขึ้นเอง นักวิทยาศาสตร์ยังคงถกเถียงกันว่าทำไม — ตั้งแต่การรวบรวมความทรงจำไปจนถึงการประมวลผลอารมณ์ ทฤษฎีต่างๆ น่าสนใจและบางครั้งขัดแย้งกัน วิดีโอจาก Be Smart นี้เจาะลึกงานวิจัยทางประสาทวิทยาล่าสุดเกี่ยวกับการฝัน สำรวจสิ่งที่เกิดขึ้นในสมองระหว่างการนอนหลับ REM และทำไมมันอาจสำคัญกว่าที่คุณคิด มาสำรวจวิทยาศาสตร์เบื้องหลังการผจญภัยยามค่ำคืนของคุณกัน",
    follow_up_suggestions: ["เกิดอะไรขึ้นระหว่างการนอนหลับ REM?", "เราควบคุมความฝันได้ไหม?", "ทำไมบางคนไม่เคยจำความฝันได้เลย?"],
  },
  cs: {
    phrase: "Proč váš mozek vytváří celé světy, zatímco spíte?",
    title: "Neurověda snění",
    assistant_response: "Každou noc váš mozek vstupuje do podivného světa vlastní tvorby. Vědci stále debatují proč — od konsolidace paměti po emocionální zpracování, teorie jsou fascinující a někdy rozporuplné. Toto video od Be Smart se ponoří do nejnovějšího neurovědního výzkumu snění a zkoumá, co se děje ve vašem mozku během REM spánku a proč to může být důležitější, než si myslíte. Pojďme prozkoumat vědu za vašimi nočními dobrodružstvími.",
    follow_up_suggestions: ["Co se děje během REM spánku?", "Můžeme ovládat své sny?", "Proč si někteří lidé sny nikdy nepamatují?"],
  },
  sv: {
    phrase: "Varför skapar din hjärna hela världar medan du sover?",
    title: "Drömmarnas neurovetenskap",
    assistant_response: "Varje natt träder din hjärna in i en märklig värld av eget skapande. Forskare debatterar fortfarande varför — från minneskonsolidering till emotionell bearbetning, teorierna är fascinerande och ibland motsägelsefulla. Den här videon från Be Smart dyker ner i den senaste neurovetenskapliga forskningen om drömmar och utforskar vad som händer i din hjärna under REM-sömn och varför det kan vara viktigare än du tror. Låt oss utforska vetenskapen bakom dina nattliga äventyr.",
    follow_up_suggestions: ["Vad händer under REM-sömnen?", "Kan vi styra våra drömmar?", "Varför minns vissa aldrig sina drömmar?"],
  },
  he: {
    phrase: "למה המוח שלך יוצר עולמות שלמים בזמן שאתה ישן?",
    title: "מדעי המוח של חלומות",
    assistant_response: "בכל לילה המוח שלך נכנס לעולם מוזר שהוא עצמו יצר. מדענים עדיין מתווכחים מדוע — מאיחוד זיכרונות ועד עיבוד רגשי, התיאוריות מרתקות ולפעמים סותרות. הסרטון הזה מ-Be Smart צולל למחקר הנוירו-מדעי העדכני ביותר על חלומות, חוקר מה קורה במוח שלך במהלך שנת REM ולמה זה עשוי להיות חשוב יותר ממה שאתה חושב. בואו נחקור את המדע שמאחורי הרפתקאות הלילה שלך.",
    follow_up_suggestions: ["מה קורה במהלך שנת REM?", "האם אפשר לשלוט בחלומות?", "למה חלק מהאנשים לא זוכרים חלומות?"],
  },
};

const ENIAC_TEXT: Record<string, InspirationText> = {
  en: {
    phrase: "Who were the six women that programmed the first computer — and why were they erased from history?",
    title: "The forgotten first programmers",
    assistant_response: "In 1945, six brilliant women programmed ENIAC — the world's first general-purpose electronic computer — entirely without programming languages or manuals. When the machine was unveiled to the world, they were never introduced. Their names were erased from history for decades. Kathy Kleiman's TEDx talk uncovers their extraordinary story and the detective work it took to find them. Let's discover the pioneers who shaped the digital age.",
    follow_up_suggestions: ["Who were the six ENIAC programmers?", "How did they program without a language?", "What other women shaped early computing?"],
  },
  de: {
    phrase: "Wer waren die sechs Frauen, die den ersten Computer programmierten — und warum wurden sie aus der Geschichte gelöscht?",
    title: "Die vergessenen ersten Programmiererinnen",
    assistant_response: "1945 programmierten sechs brillante Frauen ENIAC — den weltweit ersten elektronischen Universalcomputer — ganz ohne Programmiersprachen oder Handbücher. Als die Maschine der Welt vorgestellt wurde, wurden sie nie erwähnt. Ihre Namen wurden jahrzehntelang aus der Geschichte gelöscht. Kathy Kleimans TEDx-Vortrag enthüllt ihre außergewöhnliche Geschichte und die Detektivarbeit, die nötig war, um sie zu finden. Entdecken wir die Pionierinnen, die das digitale Zeitalter geprägt haben.",
    follow_up_suggestions: ["Wer waren die sechs ENIAC-Programmiererinnen?", "Wie haben sie ohne Programmiersprache programmiert?", "Welche anderen Frauen prägten die frühe Informatik?"],
  },
  zh: {
    phrase: "谁是编程第一台计算机的六位女性——她们为何被历史遗忘？",
    title: "被遗忘的首批程序员",
    assistant_response: "1945年，六位杰出的女性编写了ENIAC程序——世界上第一台通用电子计算机——完全没有编程语言或手册。当机器向世界展示时，她们从未被介绍。几十年来，她们的名字被从历史中抹去。Kathy Kleiman的TEDx演讲揭示了她们非凡的故事以及寻找她们所付出的侦探工作。让我们一起发现塑造数字时代的先驱者。",
    follow_up_suggestions: ["六位ENIAC程序员是谁？", "没有编程语言她们如何编程？", "还有哪些女性影响了早期计算？"],
  },
  es: {
    phrase: "¿Quiénes fueron las seis mujeres que programaron la primera computadora — y por qué fueron borradas de la historia?",
    title: "Las primeras programadoras olvidadas",
    assistant_response: "En 1945, seis mujeres brillantes programaron ENIAC — la primera computadora electrónica de propósito general del mundo — sin lenguajes de programación ni manuales. Cuando la máquina fue presentada al mundo, nunca fueron mencionadas. Sus nombres fueron borrados de la historia durante décadas. La charla TEDx de Kathy Kleiman descubre su extraordinaria historia y el trabajo detectivesco necesario para encontrarlas. Descubramos a las pioneras que moldearon la era digital.",
    follow_up_suggestions: ["¿Quiénes fueron las seis programadoras de ENIAC?", "¿Cómo programaron sin un lenguaje?", "¿Qué otras mujeres dieron forma a la computación temprana?"],
  },
  fr: {
    phrase: "Qui étaient les six femmes qui ont programmé le premier ordinateur — et pourquoi ont-elles été effacées de l'histoire ?",
    title: "Les premières programmeuses oubliées",
    assistant_response: "En 1945, six femmes brillantes ont programmé l'ENIAC — le premier ordinateur électronique universel au monde — entièrement sans langages de programmation ni manuels. Lorsque la machine a été présentée au monde, elles n'ont jamais été mentionnées. Leurs noms ont été effacés de l'histoire pendant des décennies. La conférence TEDx de Kathy Kleiman révèle leur histoire extraordinaire et le travail de détective nécessaire pour les retrouver. Découvrons les pionnières qui ont façonné l'ère numérique.",
    follow_up_suggestions: ["Qui étaient les six programmeuses de l'ENIAC ?", "Comment ont-elles programmé sans langage ?", "Quelles autres femmes ont marqué l'informatique ?"],
  },
  pt: {
    phrase: "Quem foram as seis mulheres que programaram o primeiro computador — e por que foram apagadas da história?",
    title: "As primeiras programadoras esquecidas",
    assistant_response: "Em 1945, seis mulheres brilhantes programaram o ENIAC — o primeiro computador eletrônico de uso geral do mundo — inteiramente sem linguagens de programação ou manuais. Quando a máquina foi apresentada ao mundo, elas nunca foram mencionadas. Seus nomes foram apagados da história por décadas. A palestra TEDx de Kathy Kleiman revela sua história extraordinária e o trabalho detetivesco necessário para encontrá-las. Vamos descobrir as pioneiras que moldaram a era digital.",
    follow_up_suggestions: ["Quem foram as seis programadoras do ENIAC?", "Como elas programaram sem uma linguagem?", "Que outras mulheres moldaram a computação?"],
  },
  ru: {
    phrase: "Кто были шесть женщин, запрограммировавших первый компьютер — и почему их стёрли из истории?",
    title: "Забытые первые программистки",
    assistant_response: "В 1945 году шесть блестящих женщин запрограммировали ENIAC — первый в мире универсальный электронный компьютер — полностью без языков программирования и руководств. Когда машину представили миру, их даже не упомянули. Их имена были стёрты из истории на десятилетия. TEDx-выступление Кэти Клейман раскрывает их необыкновенную историю и детективную работу по их поиску. Давайте откроем для себя пионерок, сформировавших цифровую эпоху.",
    follow_up_suggestions: ["Кто были шесть программисток ENIAC?", "Как они программировали без языка?", "Какие ещё женщины повлияли на раннюю информатику?"],
  },
  ja: {
    phrase: "最初のコンピュータをプログラムした6人の女性は誰で、なぜ歴史から消されたのか？",
    title: "忘れられた最初のプログラマーたち",
    assistant_response: "1945年、6人の優秀な女性がENIAC（世界初の汎用電子コンピュータ）をプログラミングしました。プログラミング言語もマニュアルもない状態で。マシンが世界に公開されたとき、彼女たちは紹介されませんでした。数十年間、彼女たちの名前は歴史から消されていました。Kathy KleimanのTEDxトークは、彼女たちの並外れた物語と、彼女たちを見つけるための調査を明らかにします。デジタル時代を形作った先駆者たちを発見しましょう。",
    follow_up_suggestions: ["ENIACの6人のプログラマーは誰？", "言語なしでどうプログラムした？", "他にどの女性が初期のコンピューティングに貢献した？"],
  },
  ko: {
    phrase: "최초의 컴퓨터를 프로그래밍한 여섯 여성은 누구이며, 왜 역사에서 지워졌을까요?",
    title: "잊혀진 최초의 프로그래머들",
    assistant_response: "1945년, 여섯 명의 뛰어난 여성이 세계 최초의 범용 전자 컴퓨터인 ENIAC을 프로그래밍 언어도 매뉴얼도 없이 프로그래밍했습니다. 기계가 세상에 공개되었을 때 그들은 소개조차 되지 않았습니다. 수십 년 동안 그들의 이름은 역사에서 지워졌습니다. Kathy Kleiman의 TEDx 강연은 그들의 놀라운 이야기와 그들을 찾기 위한 추적 작업을 밝혀줍니다. 디지털 시대를 만든 선구자들을 만나봅시다.",
    follow_up_suggestions: ["ENIAC의 6명의 프로그래머는 누구인가요?", "프로그래밍 언어 없이 어떻게 프로그래밍했나요?", "초기 컴퓨팅에 기여한 다른 여성은?"],
  },
  it: {
    phrase: "Chi erano le sei donne che programmarono il primo computer — e perché furono cancellate dalla storia?",
    title: "Le prime programmatrici dimenticate",
    assistant_response: "Nel 1945, sei donne brillanti programmarono l'ENIAC — il primo computer elettronico universale al mondo — interamente senza linguaggi di programmazione né manuali. Quando la macchina fu presentata al mondo, non furono mai menzionate. I loro nomi furono cancellati dalla storia per decenni. Il TEDx talk di Kathy Kleiman svela la loro straordinaria storia e il lavoro investigativo necessario per ritrovarle. Scopriamo le pioniere che hanno plasmato l'era digitale.",
    follow_up_suggestions: ["Chi erano le sei programmatrici dell'ENIAC?", "Come hanno programmato senza un linguaggio?", "Quali altre donne hanno plasmato l'informatica?"],
  },
  tr: {
    phrase: "İlk bilgisayarı programlayan altı kadın kimdi — ve neden tarihten silindiler?",
    title: "Unutulan ilk programcılar",
    assistant_response: "1945'te altı parlak kadın, dünyanın ilk genel amaçlı elektronik bilgisayarı olan ENIAC'ı programlama dilleri veya kılavuzlar olmadan programladı. Makine dünyaya tanıtıldığında, isimleri hiç anılmadı. Onlarca yıl boyunca tarihin sayfalarından silindiler. Kathy Kleiman'ın TEDx konuşması, onların olağanüstü hikâyesini ve onları bulmak için gereken dedektiflik çalışmasını ortaya koyuyor. Dijital çağı şekillendiren öncüleri keşfedelim.",
    follow_up_suggestions: ["Altı ENIAC programcısı kimlerdi?", "Programlama dili olmadan nasıl programladılar?", "Erken dönem bilişimi şekillendiren diğer kadınlar?"],
  },
  vi: {
    phrase: "Sáu người phụ nữ lập trình chiếc máy tính đầu tiên là ai — và tại sao họ bị xóa khỏi lịch sử?",
    title: "Những lập trình viên đầu tiên bị lãng quên",
    assistant_response: "Năm 1945, sáu người phụ nữ tài năng đã lập trình ENIAC — máy tính điện tử đa năng đầu tiên trên thế giới — hoàn toàn không có ngôn ngữ lập trình hay hướng dẫn sử dụng. Khi chiếc máy được giới thiệu với thế giới, họ chưa từng được nhắc đến. Tên của họ bị xóa khỏi lịch sử suốt nhiều thập kỷ. Bài nói TEDx của Kathy Kleiman hé lộ câu chuyện phi thường và công việc thám tử để tìm ra họ. Hãy khám phá những người tiên phong đã định hình kỷ nguyên số.",
    follow_up_suggestions: ["Sáu lập trình viên ENIAC là ai?", "Họ lập trình như thế nào khi không có ngôn ngữ?", "Những phụ nữ nào khác đã định hình ngành máy tính?"],
  },
  id: {
    phrase: "Siapa enam wanita yang memprogram komputer pertama — dan mengapa mereka dihapus dari sejarah?",
    title: "Programmer pertama yang terlupakan",
    assistant_response: "Pada tahun 1945, enam wanita brilian memprogram ENIAC — komputer elektronik serbaguna pertama di dunia — tanpa bahasa pemrograman atau manual. Ketika mesin itu diperkenalkan ke dunia, mereka tidak pernah disebutkan. Nama mereka dihapus dari sejarah selama puluhan tahun. Presentasi TEDx Kathy Kleiman mengungkap kisah luar biasa mereka dan kerja detektif yang diperlukan untuk menemukan mereka. Mari temukan para pelopor yang membentuk era digital.",
    follow_up_suggestions: ["Siapa enam programmer ENIAC?", "Bagaimana mereka memprogram tanpa bahasa?", "Wanita lain yang membentuk komputasi awal?"],
  },
  pl: {
    phrase: "Kim było sześć kobiet, które zaprogramowały pierwszy komputer — i dlaczego wymazano je z historii?",
    title: "Zapomniane pierwsze programistki",
    assistant_response: "W 1945 roku sześć genialnych kobiet zaprogramowało ENIAC — pierwszy na świecie uniwersalny komputer elektroniczny — całkowicie bez języków programowania i podręczników. Gdy maszynę zaprezentowano światu, nigdy ich nie wymieniono. Ich nazwiska zostały wymazane z historii na dziesięciolecia. Wykład TEDx Kathy Kleiman odkrywa ich niezwykłą historię i detektywistyczną pracę potrzebną do ich odnalezienia. Odkryjmy pionierki, które ukształtowały erę cyfrową.",
    follow_up_suggestions: ["Kim było sześć programistek ENIAC?", "Jak programowały bez języka programowania?", "Jakie inne kobiety kształtowały wczesną informatykę?"],
  },
  nl: {
    phrase: "Wie waren de zes vrouwen die de eerste computer programmeerden — en waarom werden ze uit de geschiedenis gewist?",
    title: "De vergeten eerste programmeurs",
    assistant_response: "In 1945 programmeerden zes briljante vrouwen ENIAC — 's werelds eerste universele elektronische computer — geheel zonder programmeertalen of handleidingen. Toen de machine aan de wereld werd gepresenteerd, werden ze nooit genoemd. Hun namen werden decennialang uit de geschiedenis gewist. Kathy Kleimans TEDx-talk onthult hun buitengewone verhaal en het speurwerk dat nodig was om hen te vinden. Laten we de pioniers ontdekken die het digitale tijdperk hebben gevormd.",
    follow_up_suggestions: ["Wie waren de zes ENIAC-programmeurs?", "Hoe programmeerden ze zonder taal?", "Welke andere vrouwen vormden de vroege informatica?"],
  },
  ar: {
    phrase: "من هن النساء الست اللواتي برمجن أول حاسوب — ولماذا مُحين من التاريخ؟",
    title: "أول مبرمجات منسيات",
    assistant_response: "في عام 1945، قامت ست نساء رائعات ببرمجة ENIAC — أول حاسوب إلكتروني عام في العالم — بالكامل بدون لغات برمجة أو أدلة. عندما قُدم الجهاز للعالم، لم يُذكرن أبداً. مُحيت أسماؤهن من التاريخ لعقود. يكشف حديث TEDx لكاثي كلايمان قصتهن الاستثنائية والعمل البوليسي المطلوب للعثور عليهن. دعونا نكتشف الرائدات اللواتي شكّلن العصر الرقمي.",
    follow_up_suggestions: ["من هن مبرمجات ENIAC الست؟", "كيف برمجن بدون لغة برمجة؟", "أي نساء أخريات أثّرن في الحوسبة المبكرة؟"],
  },
  hi: {
    phrase: "पहले कंप्यूटर को प्रोग्राम करने वाली छह महिलाएं कौन थीं — और उन्हें इतिहास से क्यों मिटा दिया गया?",
    title: "भुला दी गई पहली प्रोग्रामर",
    assistant_response: "1945 में, छह प्रतिभाशाली महिलाओं ने ENIAC — दुनिया का पहला सामान्य-उद्देश्य इलेक्ट्रॉनिक कंप्यूटर — को बिना किसी प्रोग्रामिंग भाषा या मैनुअल के प्रोग्राम किया। जब मशीन को दुनिया के सामने पेश किया गया, तो उनका नाम तक नहीं लिया गया। दशकों तक उनके नाम इतिहास से मिटा दिए गए। Kathy Kleiman की TEDx बातचीत उनकी असाधारण कहानी और उन्हें खोजने के लिए की गई जासूसी को उजागर करती है। आइए डिजिटल युग को आकार देने वाली अग्रणी महिलाओं को जानें।",
    follow_up_suggestions: ["ENIAC की छह प्रोग्रामर कौन थीं?", "बिना भाषा के कैसे प्रोग्रामिंग की?", "शुरुआती कंप्यूटिंग में और कौन सी महिलाओं का योगदान?"],
  },
  th: {
    phrase: "หกผู้หญิงที่เขียนโปรแกรมคอมพิวเตอร์เครื่องแรกเป็นใคร — และทำไมพวกเธอถูกลบออกจากประวัติศาสตร์?",
    title: "โปรแกรมเมอร์คนแรกที่ถูกลืม",
    assistant_response: "ในปี 1945 หญิงสาวหกคนที่ชาญฉลาดได้เขียนโปรแกรม ENIAC — คอมพิวเตอร์อิเล็กทรอนิกส์อเนกประสงค์เครื่องแรกของโลก — โดยไม่มีภาษาโปรแกรมหรือคู่มือใดๆ เมื่อเครื่องถูกเปิดตัวต่อสาธารณะ พวกเธอไม่เคยได้รับการแนะนำ ชื่อของพวกเธอถูกลบจากประวัติศาสตร์หลายทศวรรษ การบรรยาย TEDx ของ Kathy Kleiman เปิดเผยเรื่องราวอันน่าทึ่งและการสืบสวนเพื่อค้นหาพวกเธอ มาค้นพบผู้บุกเบิกที่หล่อหลอมยุคดิจิทัลกัน",
    follow_up_suggestions: ["โปรแกรมเมอร์หกคนของ ENIAC คือใคร?", "พวกเธอเขียนโปรแกรมโดยไม่มีภาษาได้อย่างไร?", "ผู้หญิงคนอื่นที่มีบทบาทในคอมพิวเตอร์ยุคแรก?"],
  },
  cs: {
    phrase: "Kdo bylo šest žen, které naprogramovaly první počítač — a proč byly vymazány z historie?",
    title: "Zapomenuté první programátorky",
    assistant_response: "V roce 1945 šest brilantních žen naprogramovalo ENIAC — první univerzální elektronický počítač na světě — zcela bez programovacích jazyků nebo příruček. Když byl stroj představen světu, nikdy nebyly zmíněny. Jejich jména byla z historie vymazána na celá desetiletí. TEDx přednáška Kathy Kleiman odhaluje jejich mimořádný příběh a detektivní práci potřebnou k jejich nalezení. Objevme průkopnice, které formovaly digitální věk.",
    follow_up_suggestions: ["Kdo bylo šest programátorek ENIACu?", "Jak programovaly bez jazyka?", "Které další ženy formovaly rané počítače?"],
  },
  sv: {
    phrase: "Vilka var de sex kvinnorna som programmerade den första datorn — och varför raderades de ur historien?",
    title: "De bortglömda första programmerarna",
    assistant_response: "1945 programmerade sex briljanta kvinnor ENIAC — världens första elektroniska universaldator — helt utan programspråk eller manualer. När maskinen presenterades för världen nämndes de aldrig. Deras namn raderades ur historien i årtionden. Kathy Kleimans TEDx-föredrag avslöjar deras extraordinära historia och detektivarbetet som krävdes för att hitta dem. Låt oss upptäcka pionjärerna som formade den digitala tidsåldern.",
    follow_up_suggestions: ["Vilka var ENIACs sex programmerare?", "Hur programmerade de utan språk?", "Vilka andra kvinnor formade tidig databehandling?"],
  },
  he: {
    phrase: "מי היו שש הנשים שתכנתו את המחשב הראשון — ולמה הן נמחקו מההיסטוריה?",
    title: "המתכנתות הראשונות שנשכחו",
    assistant_response: "ב-1945, שש נשים מבריקות תכנתו את ENIAC — המחשב האלקטרוני הראשון לשימוש כללי בעולם — לחלוטין ללא שפות תכנות או מדריכים. כשהמכונה הוצגה לעולם, שמותיהן לא הוזכרו. הן נמחקו מההיסטוריה במשך עשרות שנים. הרצאת TEDx של קתי קליימן חושפת את סיפורן המיוחד ואת עבודת הבילוש שנדרשה למצוא אותן. בואו נגלה את החלוצות שעיצבו את העידן הדיגיטלי.",
    follow_up_suggestions: ["מי היו שש מתכנתות ENIAC?", "איך הן תכנתו בלי שפה?", "אילו נשים נוספות עיצבו את המחשוב המוקדם?"],
  },
};

const URBAN_FARMS_TEXT: Record<string, InspirationText> = {
  en: {
    phrase: "What happens when a city turns its vacant lots into farms?",
    title: "Urban gardens vs food deserts",
    assistant_response: "In many cities, entire neighborhoods lack access to fresh, affordable food — these are called food deserts. But a growing movement of urban farmers is turning vacant lots and rooftops into thriving gardens that feed communities. Devita Davison's TED talk shows how Detroit became an unlikely leader in this revolution, proving that agriculture and activism can go hand in hand. Let's explore how cities are growing their own future.",
    follow_up_suggestions: ["What exactly is a food desert?", "How do community gardens get started?", "Which cities lead in urban farming?"],
  },
  de: {
    phrase: "Was passiert, wenn eine Stadt ihre Brachflächen in Farmen verwandelt?",
    title: "Stadtgärten gegen Lebensmittelwüsten",
    assistant_response: "In vielen Städten haben ganze Viertel keinen Zugang zu frischen, bezahlbaren Lebensmitteln — man nennt sie Lebensmittelwüsten. Doch eine wachsende Bewegung urbaner Landwirte verwandelt Brachflächen und Dächer in blühende Gärten, die Gemeinschaften ernähren. Devita Davisons TED-Vortrag zeigt, wie Detroit zu einem unerwarteten Vorreiter dieser Revolution wurde und beweist, dass Landwirtschaft und Aktivismus Hand in Hand gehen können. Entdecken wir, wie Städte ihre eigene Zukunft anbauen.",
    follow_up_suggestions: ["Was genau ist eine Lebensmittelwüste?", "Wie entstehen Gemeinschaftsgärten?", "Welche Städte sind führend in urbaner Landwirtschaft?"],
  },
  zh: {
    phrase: "当一座城市把空地变成农场会发生什么？",
    title: "城市花园对抗食品荒漠",
    assistant_response: "在许多城市，整个社区都无法获得新鲜、实惠的食物——这些地方被称为食品荒漠。但越来越多的城市农民正在把空地和屋顶变成繁荣的花园来养活社区。Devita Davison的TED演讲展示了底特律如何成为这场革命中意想不到的领导者，证明农业和行动主义可以携手并进。让我们探索城市如何种出自己的未来。",
    follow_up_suggestions: ["食品荒漠究竟是什么？", "社区花园是如何开始的？", "哪些城市在城市农业方面领先？"],
  },
  es: {
    phrase: "¿Qué sucede cuando una ciudad convierte sus terrenos vacíos en granjas?",
    title: "Huertos urbanos contra desiertos alimentarios",
    assistant_response: "En muchas ciudades, barrios enteros carecen de acceso a alimentos frescos y asequibles — se llaman desiertos alimentarios. Pero un movimiento creciente de agricultores urbanos está convirtiendo terrenos vacíos y azoteas en jardines prósperos que alimentan comunidades. La charla TED de Devita Davison muestra cómo Detroit se convirtió en un líder inesperado de esta revolución, demostrando que agricultura y activismo pueden ir de la mano. Exploremos cómo las ciudades cultivan su propio futuro.",
    follow_up_suggestions: ["¿Qué es exactamente un desierto alimentario?", "¿Cómo se inician los huertos comunitarios?", "¿Qué ciudades lideran la agricultura urbana?"],
  },
  fr: {
    phrase: "Que se passe-t-il quand une ville transforme ses terrains vagues en fermes ?",
    title: "Jardins urbains contre déserts alimentaires",
    assistant_response: "Dans beaucoup de villes, des quartiers entiers n'ont pas accès à une alimentation fraîche et abordable — on les appelle des déserts alimentaires. Mais un mouvement croissant d'agriculteurs urbains transforme les terrains vagues et toits en jardins florissants qui nourrissent les communautés. Le TED talk de Devita Davison montre comment Detroit est devenu un leader inattendu de cette révolution, prouvant que agriculture et activisme peuvent aller de pair. Explorons comment les villes cultivent leur propre avenir.",
    follow_up_suggestions: ["Qu'est-ce qu'un désert alimentaire ?", "Comment démarrer un jardin communautaire ?", "Quelles villes sont pionnières en agriculture urbaine ?"],
  },
  pt: {
    phrase: "O que acontece quando uma cidade transforma seus terrenos vazios em fazendas?",
    title: "Hortas urbanas contra desertos alimentares",
    assistant_response: "Em muitas cidades, bairros inteiros não têm acesso a alimentos frescos e acessíveis — são os chamados desertos alimentares. Mas um movimento crescente de agricultores urbanos está transformando terrenos vazios e terraços em hortas prósperas que alimentam comunidades. A palestra TED de Devita Davison mostra como Detroit se tornou uma líder improvável nesta revolução, provando que agricultura e ativismo podem andar juntos. Vamos explorar como as cidades estão cultivando seu próprio futuro.",
    follow_up_suggestions: ["O que exatamente é um deserto alimentar?", "Como começar uma horta comunitária?", "Quais cidades lideram a agricultura urbana?"],
  },
  ru: {
    phrase: "Что произойдёт, если город превратит пустыри в фермы?",
    title: "Городские сады против продовольственных пустынь",
    assistant_response: "Во многих городах целые районы лишены доступа к свежей и доступной еде — их называют продовольственными пустынями. Но растущее движение городских фермеров превращает пустыри и крыши в цветущие сады, которые кормят сообщества. TED-выступление Девиты Дэвисон показывает, как Детройт стал неожиданным лидером этой революции, доказывая, что сельское хозяйство и активизм могут идти рука об руку. Давайте исследуем, как города выращивают своё собственное будущее.",
    follow_up_suggestions: ["Что такое продовольственная пустыня?", "Как создаются общественные сады?", "Какие города лидируют в городском фермерстве?"],
  },
  ja: {
    phrase: "都市が空き地を農場に変えたら何が起きる？",
    title: "都市農園とフードデザート",
    assistant_response: "多くの都市で、新鮮で手頃な食料にアクセスできない地域が丸ごと存在します — フードデザートと呼ばれています。しかし、都市農業者の運動が成長し、空き地や屋上を活気あふれる菜園に変え、地域社会を養っています。Devita DavisonのTEDトークは、デトロイトがいかにしてこの革命の予想外のリーダーとなったかを示し、農業と行動主義が手を携えることができることを証明しています。都市がどのように自らの未来を育てているか探りましょう。",
    follow_up_suggestions: ["フードデザートとは何？", "コミュニティガーデンはどう始まる？", "都市農業をリードする都市は？"],
  },
  ko: {
    phrase: "도시가 빈 땅을 농장으로 바꾸면 어떤 일이 일어날까요?",
    title: "도시 농업과 식품 사막",
    assistant_response: "많은 도시에서 신선하고 저렴한 식품에 접근할 수 없는 지역이 있습니다 — 이를 식품 사막이라고 합니다. 하지만 도시 농부들의 움직임이 빈 땅과 옥상을 번성하는 텃밭으로 바꾸며 지역사회를 먹여 살리고 있습니다. Devita Davison의 TED 강연은 디트로이트가 어떻게 이 혁명의 예상 밖의 리더가 되었는지 보여주며, 농업과 행동주의가 함께할 수 있음을 증명합니다. 도시가 어떻게 자신의 미래를 키우고 있는지 탐구해봅시다.",
    follow_up_suggestions: ["식품 사막이 정확히 무엇인가요?", "커뮤니티 가든은 어떻게 시작하나요?", "어떤 도시가 도시 농업을 선도하나요?"],
  },
  it: {
    phrase: "Cosa succede quando una città trasforma i suoi terreni vuoti in fattorie?",
    title: "Orti urbani contro deserti alimentari",
    assistant_response: "In molte città, interi quartieri non hanno accesso a cibo fresco e accessibile — si chiamano deserti alimentari. Ma un movimento crescente di agricoltori urbani sta trasformando terreni vuoti e tetti in orti fiorenti che nutrono le comunità. Il TED talk di Devita Davison mostra come Detroit sia diventata un leader inaspettato di questa rivoluzione, dimostrando che agricoltura e attivismo possono andare di pari passo. Esploriamo come le città coltivano il proprio futuro.",
    follow_up_suggestions: ["Cos'è esattamente un deserto alimentare?", "Come si avvia un orto comunitario?", "Quali città guidano l'agricoltura urbana?"],
  },
  tr: {
    phrase: "Bir şehir boş arazilerini çiftliğe dönüştürürse ne olur?",
    title: "Kent bahçeleri ve gıda çölleri",
    assistant_response: "Birçok şehirde, taze ve uygun fiyatlı gıdaya erişimi olmayan mahalleler var — bunlara gıda çölleri deniyor. Ancak büyüyen bir kent çiftçileri hareketi, boş arazileri ve çatıları toplulukları besleyen verimli bahçelere dönüştürüyor. Devita Davison'ın TED konuşması, Detroit'in bu devrimin beklenmedik lideri haline nasıl geldiğini gösteriyor ve tarımla aktivizmin el ele yürüyebileceğini kanıtlıyor. Şehirlerin kendi geleceklerini nasıl yetiştirdiğini keşfedelim.",
    follow_up_suggestions: ["Gıda çölü tam olarak nedir?", "Topluluk bahçeleri nasıl başlar?", "Kent tarımında hangi şehirler öncü?"],
  },
  vi: {
    phrase: "Điều gì xảy ra khi một thành phố biến đất trống thành nông trại?",
    title: "Vườn đô thị và sa mạc thực phẩm",
    assistant_response: "Ở nhiều thành phố, cả khu dân cư không có quyền tiếp cận thực phẩm tươi và giá cả phải chăng — đây gọi là sa mạc thực phẩm. Nhưng phong trào nông dân đô thị đang biến đất trống và mái nhà thành vườn tươi tốt nuôi sống cộng đồng. Bài nói TED của Devita Davison cho thấy Detroit đã trở thành nhà lãnh đạo bất ngờ của cuộc cách mạng này, chứng minh nông nghiệp và hành động xã hội có thể song hành. Hãy khám phá cách các thành phố đang vun trồng tương lai của mình.",
    follow_up_suggestions: ["Sa mạc thực phẩm chính xác là gì?", "Vườn cộng đồng bắt đầu như thế nào?", "Thành phố nào dẫn đầu về nông nghiệp đô thị?"],
  },
  id: {
    phrase: "Apa yang terjadi ketika sebuah kota mengubah lahan kosongnya menjadi pertanian?",
    title: "Kebun kota melawan gurun pangan",
    assistant_response: "Di banyak kota, seluruh lingkungan tidak memiliki akses ke makanan segar dan terjangkau — ini disebut gurun pangan. Namun gerakan petani kota yang berkembang mengubah lahan kosong dan atap menjadi kebun subur yang memberi makan komunitas. Presentasi TED Devita Davison menunjukkan bagaimana Detroit menjadi pemimpin tak terduga dalam revolusi ini, membuktikan bahwa pertanian dan aktivisme bisa berjalan beriringan. Mari jelajahi bagaimana kota-kota menanam masa depan mereka sendiri.",
    follow_up_suggestions: ["Apa sebenarnya gurun pangan itu?", "Bagaimana kebun komunitas dimulai?", "Kota mana yang memimpin pertanian kota?"],
  },
  pl: {
    phrase: "Co się dzieje, gdy miasto zamienia pustostany w farmy?",
    title: "Ogrody miejskie kontra pustynie żywnościowe",
    assistant_response: "W wielu miastach całe dzielnice nie mają dostępu do świeżej, przystępnej cenowo żywności — nazywa się je pustyniami żywnościowymi. Ale rosnący ruch miejskich rolników zamienia pustostany i dachy w kwitnące ogrody, które karmią społeczności. Wykład TED Devity Davison pokazuje, jak Detroit stało się niespodziewanym liderem tej rewolucji, udowadniając, że rolnictwo i aktywizm mogą iść w parze. Odkryjmy, jak miasta uprawiają własną przyszłość.",
    follow_up_suggestions: ["Czym dokładnie jest pustynia żywnościowa?", "Jak powstają ogrody społeczne?", "Które miasta przodują w rolnictwie miejskim?"],
  },
  nl: {
    phrase: "Wat gebeurt er als een stad haar braakliggende grond in boerderijen verandert?",
    title: "Stadstuinen tegen voedselwoestijnen",
    assistant_response: "In veel steden hebben hele wijken geen toegang tot verse, betaalbare voeding — dit worden voedselwoestijnen genoemd. Maar een groeiende beweging van stadsboeren verandert braakliggende terreinen en daken in bloeiende tuinen die gemeenschappen voeden. Devita Davisons TED-talk laat zien hoe Detroit een onverwachte leider werd in deze revolutie en bewijst dat landbouw en activisme hand in hand kunnen gaan. Laten we ontdekken hoe steden hun eigen toekomst kweken.",
    follow_up_suggestions: ["Wat is precies een voedselwoestijn?", "Hoe begin je een gemeenschapstuin?", "Welke steden lopen voorop in stadslandbouw?"],
  },
  ar: {
    phrase: "ماذا يحدث عندما تحوّل مدينة أراضيها الفارغة إلى مزارع؟",
    title: "حدائق المدن ضد صحاري الغذاء",
    assistant_response: "في كثير من المدن، أحياء بأكملها تفتقر إلى الغذاء الطازج والميسور — تُسمى صحاري الغذاء. لكن حركة متنامية من المزارعين الحضريين تحوّل الأراضي الفارغة والأسطح إلى حدائق مزدهرة تطعم المجتمعات. يُظهر حديث TED لديفيتا دافيسون كيف أصبحت ديترويت قائدة غير متوقعة لهذه الثورة، مثبتة أن الزراعة والنشاط الاجتماعي يمكن أن يسيرا جنباً إلى جنب. دعونا نستكشف كيف تزرع المدن مستقبلها.",
    follow_up_suggestions: ["ما هي صحراء الغذاء بالتحديد؟", "كيف تبدأ الحدائق المجتمعية؟", "أي المدن تقود الزراعة الحضرية؟"],
  },
  hi: {
    phrase: "जब कोई शहर अपनी खाली ज़मीन को खेत में बदल दे तो क्या होता है?",
    title: "शहरी बागवानी बनाम खाद्य मरुस्थल",
    assistant_response: "कई शहरों में, पूरे मोहल्लों में ताज़ा और सस्ता भोजन उपलब्ध नहीं है — इन्हें खाद्य मरुस्थल कहते हैं। लेकिन शहरी किसानों का बढ़ता आंदोलन खाली ज़मीनों और छतों को फलते-फूलते बगीचों में बदल रहा है जो समुदायों को खिला रहे हैं। Devita Davison की TED वार्ता दिखाती है कि डेट्रॉइट कैसे इस क्रांति का अप्रत्याशित नेता बन गया, साबित करते हुए कि कृषि और सक्रियता साथ-साथ चल सकती हैं। आइए जानें कि शहर कैसे अपना भविष्य उगा रहे हैं।",
    follow_up_suggestions: ["खाद्य मरुस्थल वास्तव में क्या है?", "सामुदायिक बगीचे कैसे शुरू होते हैं?", "शहरी खेती में कौन से शहर अग्रणी हैं?"],
  },
  th: {
    phrase: "เกิดอะไรขึ้นเมื่อเมืองเปลี่ยนที่ดินว่างเปล่าเป็นฟาร์ม?",
    title: "สวนในเมืองกับทะเลทรายอาหาร",
    assistant_response: "ในหลายเมือง ย่านทั้งหมดขาดการเข้าถึงอาหารสดในราคาที่เอื้อมถึง — เรียกว่าทะเลทรายอาหาร แต่ขบวนการเกษตรกรในเมืองที่เติบโตกำลังเปลี่ยนที่ดินว่างเปล่าและดาดฟ้าเป็นสวนที่อุดมสมบูรณ์เพื่อเลี้ยงชุมชน การบรรยาย TED ของ Devita Davison แสดงให้เห็นว่าดีทรอยต์กลายเป็นผู้นำที่ไม่คาดคิดของการปฏิวัตินี้ พิสูจน์ว่าเกษตรกรรมและการเคลื่อนไหวทางสังคมสามารถไปด้วยกันได้ มาสำรวจว่าเมืองต่างๆ กำลังปลูกอนาคตของตัวเองอย่างไร",
    follow_up_suggestions: ["ทะเลทรายอาหารคืออะไรกันแน่?", "สวนชุมชนเริ่มต้นอย่างไร?", "เมืองไหนเป็นผู้นำด้านเกษตรในเมือง?"],
  },
  cs: {
    phrase: "Co se stane, když město promění prázdné pozemky ve farmy?",
    title: "Městské zahrady proti potravinovým pouštím",
    assistant_response: "V mnoha městech nemají celé čtvrti přístup k čerstvým a dostupným potravinám — říká se jim potravinové pouště. Ale rostoucí hnutí městských farmářů proměňuje prázdné pozemky a střechy v kvetoucí zahrady, které živí komunity. TED přednáška Devity Davison ukazuje, jak se Detroit stal nečekaným lídrem této revoluce a dokázal, že zemědělství a aktivismus mohou jít ruku v ruce. Pojďme prozkoumat, jak města pěstují svou vlastní budoucnost.",
    follow_up_suggestions: ["Co přesně je potravinová poušť?", "Jak vznikají komunitní zahrady?", "Která města vedou v městském zemědělství?"],
  },
  sv: {
    phrase: "Vad händer när en stad förvandlar sina tomma tomter till odlingar?",
    title: "Stadsodling mot matöknar",
    assistant_response: "I många städer saknar hela stadsdelar tillgång till färsk och prisvärd mat — de kallas matöknar. Men en växande rörelse av stadsodlare förvandlar tomma tomter och tak till blomstrande trädgårdar som försörjer samhällen. Devita Davisons TED-föredrag visar hur Detroit blev en oväntad ledare i denna revolution och bevisar att jordbruk och aktivism kan gå hand i hand. Låt oss utforska hur städer odlar sin egen framtid.",
    follow_up_suggestions: ["Vad är egentligen en matöken?", "Hur startar man en stadsodling?", "Vilka städer leder inom stadsodling?"],
  },
  he: {
    phrase: "מה קורה כשעיר הופכת את המגרשים הריקים שלה לחוות?",
    title: "גינות עירוניות מול מדבריות מזון",
    assistant_response: "בערים רבות, שכונות שלמות חסרות גישה למזון טרי ובמחיר סביר — אלה נקראות מדבריות מזון. אבל תנועה גוברת של חקלאים עירוניים הופכת מגרשים ריקים וגגות לגינות פורחות שמזינות קהילות. הרצאת TED של דוויטה דוויסון מראה איך דטרויט הפכה למובילה בלתי צפויה של המהפכה הזו, ומוכיחה שחקלאות ואקטיביזם יכולים ללכת יד ביד. בואו נחקור איך ערים מגדלות את העתיד שלהן.",
    follow_up_suggestions: ["מהי בדיוק מדברית מזון?", "איך מתחילים גינה קהילתית?", "אילו ערים מובילות בחקלאות עירונית?"],
  },
};

// ─── Builder ─────────────────────────────────────────────────────────────────

/**
 * Return 3 hardcoded daily inspirations for the given locale.
 * Falls back to English for any unsupported locale.
 */
export function getHardcodedInspirations(locale: string): DailyInspiration[] {
  // Normalize locale: "en-US" → "en", "zh-TW" → "zh"
  const lang = locale.split("-")[0].toLowerCase();

  const dreamsT = DREAMS_TEXT[lang] ?? DREAMS_TEXT.en;
  const eniacT = ENIAC_TEXT[lang] ?? ENIAC_TEXT.en;
  const urbanT = URBAN_FARMS_TEXT[lang] ?? URBAN_FARMS_TEXT.en;

  const now = Math.floor(Date.now() / 1000);

  return [
    {
      inspiration_id: "hardcoded-dreams",
      phrase: dreamsT.phrase,
      title: dreamsT.title,
      category: "science",
      content_type: "video",
      video: { ...VIDEOS.dreams },
      generated_at: now,
      assistant_response: dreamsT.assistant_response,
      follow_up_suggestions: [...dreamsT.follow_up_suggestions],
    },
    {
      inspiration_id: "hardcoded-eniac",
      phrase: eniacT.phrase,
      title: eniacT.title,
      category: "history",
      content_type: "video",
      video: { ...VIDEOS.eniac },
      generated_at: now,
      assistant_response: eniacT.assistant_response,
      follow_up_suggestions: [...eniacT.follow_up_suggestions],
    },
    {
      inspiration_id: "hardcoded-urban-farms",
      phrase: urbanT.phrase,
      title: urbanT.title,
      category: "activism",
      content_type: "video",
      video: { ...VIDEOS.urban_farms },
      generated_at: now,
      assistant_response: urbanT.assistant_response,
      follow_up_suggestions: [...urbanT.follow_up_suggestions],
    },
  ];
}
