# backend/apps/ai/daily_inspiration/wiki_suggestions.py
# Static public Wikipedia inspirations for unauthenticated/default Daily Inspirations.
#
# Personalized users get wiki cards from wiki_generator.py. Public defaults can be
# incomplete when the daily pool has only video rows, so this module provides a
# deterministic, privacy-safe fallback with no LLM or network dependency.

import time
import uuid
from typing import List

from backend.apps.ai.daily_inspiration.schemas import DailyInspiration, DailyInspirationWiki


WIKI_TIPS = [
    {
        "title": "The Antikythera mechanism",
        "wiki_title": "Antikythera_mechanism",
        "description": "An ancient Greek hand-powered model of the cosmos.",
        "phrase": "An ancient shipwreck held a machine that predicted the sky.",
        "assistant_response": "The Antikythera mechanism is often described as the oldest known analog computer. It used bronze gears to model astronomical cycles, eclipses, and calendar timing. Open it to explore how much engineering knowledge existed more than 2,000 years ago.",
        "category": "history",
    },
    {
        "title": "Bioluminescence",
        "wiki_title": "Bioluminescence",
        "description": "Living organisms producing light through chemistry.",
        "phrase": "Some animals make their own light. The chemistry is surprisingly elegant.",
        "assistant_response": "Bioluminescence lets organisms glow for hunting, camouflage, communication, and defense. It appears across deep-sea animals, fungi, bacteria, and insects. Open it to learn how chemistry becomes light without heat.",
        "category": "science",
    },
    {
        "title": "Collective animal behavior",
        "wiki_title": "Collective_animal_behavior",
        "description": "How groups of animals coordinate movement and decisions.",
        "phrase": "Thousands of animals move as one. No conductor is in charge.",
        "assistant_response": "Collective animal behavior explains how fish schools, bird flocks, and insect swarms coordinate through local interactions. Simple responses between neighbors can create large patterns that look choreographed. Open it to explore how complex behavior can emerge from simple rules.",
        "category": "science",
    },
    {
        "title": "Library of Alexandria",
        "wiki_title": "Library_of_Alexandria",
        "description": "One of the ancient world's most famous centers of knowledge.",
        "phrase": "The ancient world's most famous library was also a research institution.",
        "assistant_response": "The Library of Alexandria was part of a larger scholarly ecosystem attached to the Mouseion. It gathered texts, hosted scholars, and became a symbol of ambitious knowledge preservation. Open it to separate the legend from what historians actually know.",
        "category": "history",
    },
    {
        "title": "Tensegrity",
        "wiki_title": "Tensegrity",
        "description": "Structures stabilized by a balance of tension and compression.",
        "phrase": "Some structures seem to float because tension does the hidden work.",
        "assistant_response": "Tensegrity structures use isolated compression elements held together by continuous tension. The result can look impossibly light while remaining stable. Open it to see why artists, architects, and biologists all care about this principle.",
        "category": "design",
    },
    {
        "title": "Fermi paradox",
        "wiki_title": "Fermi_paradox",
        "description": "The tension between likely extraterrestrial life and no clear evidence.",
        "phrase": "If the universe is so large, why does it seem so quiet?",
        "assistant_response": "The Fermi paradox asks why we have not seen convincing evidence of extraterrestrial civilizations despite the scale and age of the universe. Possible answers range from rare life to communication limits to self-destruction risks. Open it to explore one of science's biggest open questions.",
        "category": "science",
    },
]


WIKI_TIPS_DE = [
    {
        "title": "Der Mechanismus von Antikythera",
        "description": "Ein antikes griechisches, handbetriebenes Modell des Kosmos.",
        "phrase": "Ein antikes Schiffswrack barg eine Maschine, die den Himmel vorhersagte.",
        "assistant_response": "Der Mechanismus von Antikythera gilt als der älteste bekannte "
        "Analogrechner. Bronzezahnräder bildeten astronomische Zyklen, "
        "Finsternisse und Kalender ab. Entdecke, was Ingenieure vor mehr als "
        "2.000 Jahren bereits wussten.",
    },
    {
        "title": "Biolumineszenz",
        "description": "Lebende Organismen erzeugen Licht durch chemische Reaktionen.",
        "phrase": "Manche Tiere erzeugen ihr eigenes Licht. Die Chemie dahinter ist überraschend "
        "elegant.",
        "assistant_response": "Organismen leuchten für die Jagd, Tarnung, Kommunikation und "
        "Verteidigung. Das Phänomen findet sich bei Tiefseetieren, Pilzen, "
        "Bakterien und Insekten. Entdecke, wie Chemie zu Licht ohne große "
        "Wärmeentwicklung wird.",
    },
    {
        "title": "Kollektives Verhalten bei Tieren",
        "description": "Wie Tiergruppen ihre Bewegungen und Entscheidungen koordinieren.",
        "phrase": "Tausende Tiere bewegen sich wie ein einziges Wesen. Ganz ohne Dirigenten.",
        "assistant_response": "Fischschwärme, Vogelschwärme und Insektengruppen koordinieren sich "
        "durch lokale Wechselwirkungen. Einfache Reaktionen auf Nachbarn "
        "erzeugen große Muster, die choreografiert wirken. Entdecke, wie "
        "komplexes Verhalten aus einfachen Regeln entsteht.",
    },
    {
        "title": "Die Bibliothek von Alexandria",
        "description": "Eines der berühmtesten Wissenszentren der Antike.",
        "phrase": "Die berühmteste Bibliothek der Antike war auch eine Forschungseinrichtung.",
        "assistant_response": "Die Bibliothek von Alexandria gehörte zu einer größeren "
        "Gelehrtengemeinschaft am Museion. Sie sammelte Texte, beherbergte "
        "Forscher und wurde zum Sinnbild für die Bewahrung von Wissen. "
        "Entdecke, was Historiker über sie wissen und was Legende ist.",
    },
    {
        "title": "Tensegrität",
        "description": "Strukturen, die durch das Gleichgewicht von Zug und Druck stabil bleiben.",
        "phrase": "Manche Bauwerke scheinen zu schweben. Zugkräfte leisten die verborgene Arbeit.",
        "assistant_response": "Tensegritätsstrukturen verbinden einzelne Druckelemente durch ein "
        "durchgehendes Netz unter Spannung. Dadurch wirken sie erstaunlich "
        "leicht und bleiben dennoch stabil. Entdecke, warum dieses Prinzip "
        "Kunst, Architektur und Biologie beschäftigt.",
    },
    {
        "title": "Das Fermi-Paradoxon",
        "description": "Der Widerspruch zwischen möglichem außerirdischem Leben und fehlenden "
        "eindeutigen Belegen.",
        "phrase": "Wenn das Universum so groß ist, warum scheint es dann so still zu sein?",
        "assistant_response": "Das Fermi-Paradoxon fragt, warum wir trotz der Größe und des Alters "
        "des Universums keine überzeugenden Hinweise auf außerirdische "
        "Zivilisationen gefunden haben. Mögliche Antworten reichen von "
        "seltenem Leben bis zu Grenzen der Kommunikation. Entdecke eine der "
        "großen offenen Fragen der Wissenschaft.",
    },
]


def build_wiki_inspirations(count: int = 3, *, language: str = "en") -> List[DailyInspiration]:
    """Return up to ``count`` static public wiki inspiration objects."""
    now_ts = int(time.time())
    inspirations: List[DailyInspiration] = []
    for index, tip in enumerate(WIKI_TIPS[:max(0, count)]):
        content_language = "de" if language.lower().split("-")[0] == "de" else "en"
        if content_language == "de":
            tip = {**tip, **WIKI_TIPS_DE[index]}
        wiki = DailyInspirationWiki(
            title=tip["title"],
            wiki_title=tip["wiki_title"],
            description=tip["description"],
            extract=tip["assistant_response"],
        )
        inspirations.append(
            DailyInspiration(
                inspiration_id=str(uuid.uuid4()),
                language=content_language,
                phrase=tip["phrase"],
                title=tip["title"],
                assistant_response=tip["assistant_response"],
                category=tip["category"],
                content_type="wiki",
                wiki=wiki,
                generated_at=now_ts,
                follow_up_suggestions=[],
            )
        )
    return inspirations
