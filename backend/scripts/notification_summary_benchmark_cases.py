"""Synthetic, clearly labelled assistant replies for the notification summary benchmark.

Every reply is invented test data (ids start with `synthetic-`); none comes from a
user. Categories: done (task finished), partial (part of the task done, a concrete
step finished), question (reply ends in a question), long_question (long reply with
one question at the very end), info (purely informative), code (code-heavy reply).
"""
from __future__ import annotations

from dataclasses import dataclass

from backend.scripts.benchmark_postprocessing_models import Case

EXPECTED_TYPES = {'done': {'done'}, 'question': {'question'}, 'info': {'info'}, 'either': {'info', 'done'}}
_EXPECTED = {'done': 'done', 'partial': 'done', 'question': 'question', 'long_question': 'question',
             'info': 'info', 'code': 'either'}


@dataclass(frozen=True)
class NotificationCase(Case):
    expected: str = 'info'


_CODE = "```python\n" + "\n".join(f"def step_{i}(value):\n    return value + {i}" for i in range(1, 13)) + "\n```"
_BULK = {
    'en': "The two options differ in cost, setup time and long-term upkeep. Option A is cheaper at first but needs yearly maintenance, while option B costs more upfront and runs for years without attention. Both work with the current plan. ",
    'de': "Die beiden Optionen unterscheiden sich bei Kosten, Aufbauzeit und langfristigem Aufwand. Option A ist zunächst günstiger, braucht aber jährliche Wartung, Option B kostet mehr, läuft aber jahrelang ohne Pflege. Beide passen zum aktuellen Plan. ",
    'es': "Las dos opciones se diferencian en coste, tiempo de instalación y mantenimiento. La opción A es más barata al principio pero necesita revisión anual; la opción B cuesta más pero funciona años sin atención. ",
    'fr': "Les deux options diffèrent par le coût, le temps d'installation et l'entretien. L'option A est moins chère au départ mais demande un entretien annuel ; l'option B coûte plus cher mais fonctionne des années sans soin. ",
    'pt': "As duas opções diferem em custo, tempo de instalação e manutenção. A opção A é mais barata no início, mas precisa de revisão anual; a opção B custa mais e funciona anos sem cuidados. ",
    'ja': "二つの案はコスト、設置時間、長期的な手間が異なります。案Aは最初は安いですが毎年の点検が必要で、案Bは初期費用が高い代わりに何年も手間がかかりません。どちらも現在の計画に合います。",
}
# language -> category -> list of (user request, assistant reply)
_TEXT: dict[str, dict[str, list[tuple[str, str]]]] = {
    'en': {
        'done': [
            ('Add the new Gemini models to the config and run the tests.', 'I added 4 Gemini models to the provider config and ran the test suite: 31 tests pass. The changes are in providers/google.yml.'),
            ('Rename the project folder and update the links.', 'Done. I renamed the folder to "garden-notes" and fixed 7 broken links in the README.'),
            ('Book the cheapest slot for the dentist on Friday.', 'I booked the 09:30 slot on Friday at the cheapest tariff. A confirmation went to your calendar.'),
            ('Convert my budget sheet to CSV.', 'The budget sheet is converted. The CSV has 128 rows and 6 columns, saved as budget.csv.'),
            ('Fix the login bug on the settings page.', 'Fixed: the settings page no longer logs you out after saving. I added a regression test and it passes.'),
            ('Write the weekly summary email.', 'The weekly summary email is drafted and saved in your drafts. It covers the three finished tasks and the open budget question.'),
            ('Translate the onboarding text to French.', 'The onboarding text is translated into French: 14 strings in total, all placeholders checked.'),
        ],
        'partial': [
            ('Migrate all 5 services to the new database.', 'I migrated 3 of the 5 services (billing, search, mail). The remaining two fail because their schema uses a column type the new database lacks.'),
            ('Update the dependencies and run the checks.', 'Dependencies are updated and the build passes. The lint check still reports 2 unrelated warnings that I did not touch.'),
            ('Plan the trip and book the hotel.', 'The 5-day route is planned. Booking the hotel did not work because the site rejected the payment step, so nothing is booked yet.'),
            ('Clean the data and train the model.', 'The data is cleaned: 412 duplicate rows removed. Training did not start because the GPU quota is used up.'),
            ('Write chapters 1 to 3.', 'Chapters 1 and 2 are written, about 2,400 words each. Chapter 3 needs the interview notes first.'),
            ('Set up the CI pipeline.', 'The test and build stages of the pipeline run. The deploy stage is missing credentials, so it is not active.'),
        ],
        'question': [
            ('Which database should I use?', 'Both would work. Do you expect more than a few thousand writes per second?'),
            ('Help me plan the garden.', 'I can sketch the beds now. Do you want vegetables, flowers or both?'),
            ('Rewrite my cover letter.', 'Happy to. Should the tone be formal or more relaxed?'),
            ('Schedule the team meeting.', 'Tuesday and Thursday both look free. Which day do you prefer?'),
            ('Deploy the update.', 'Before I deploy: should I run the database migration at the same time?'),
            ('Make a logo.', 'I have two directions ready. Do you want the geometric one or the hand-drawn one?'),
        ],
        'long_question': [
            ('Compare the two heating options for the house.', _BULK['en'] * 3 + 'Which of the two do you want me to price in detail?'),
            ('Review the contract and tell me what to do.', _BULK['en'] * 4 + 'Do you want me to draft the counter-proposal now?'),
            ('Explain my options for the loan.', _BULK['en'] * 3 + 'Should I assume a fixed or a variable rate for the calculation?'),
            ('Help me choose a laptop.', _BULK['en'] * 3 + 'What is your budget?'),
            ('Plan the product launch.', _BULK['en'] * 4 + 'Do you want the launch on the 12th or the 19th?'),
            ('Pick a font pair for the site.', _BULK['en'] * 2 + 'Do you prefer a serif or a sans-serif heading?'),
        ],
        'info': [
            ('How does TLS work?', 'TLS sets up an encrypted channel in a handshake: the server proves its identity with a certificate, both sides agree on keys, and then traffic is encrypted with a fast symmetric cipher.'),
            ('What is the capital of Australia?', 'The capital of Australia is Canberra, not Sydney. It was founded in 1913 as a planned city.'),
            ('Explain the difference between RAM and storage.', 'RAM is fast, temporary memory for running programs. Storage keeps data permanently but is slower. A computer needs both.'),
            ('Why is the sky blue?', 'Air molecules scatter short blue wavelengths of sunlight more than long red ones, so scattered blue light reaches your eyes from every direction.'),
            ('What does a mortgage rate depend on?', 'It depends on the central bank rate, the loan term, your credit profile and the loan-to-value ratio. Fixed rates usually cost more than variable ones.'),
            ('How long should I rest a steak?', 'Rest a steak for about 5 minutes per inch of thickness, so the juices settle and do not run out when you cut it.'),
            ('What is a monad?', 'A monad is a pattern for chaining computations that carry extra context, such as optional values or errors, using a bind operation and a return operation.'),
        ],
        'code': [
            ('Show me helper functions for the steps.', 'Here are the helper functions:\n' + _CODE + '\nEach adds its own step number to the value.'),
            ('Write a parser for the config.', 'Here is a parser sketch:\n' + _CODE + '\nIt keeps each step small so you can test them separately.'),
            ('Give me example code for the pipeline.', _CODE + '\nThat is the whole pipeline; run the steps in order.'),
            ('Explain how to chain these steps.', 'Chain them like this:\n' + _CODE + '\nThe output of one step is the input of the next.'),
            ('Sketch the data model.', 'A first sketch of the data model:\n' + _CODE + '\nWe can refine the names later.'),
            ('Show a test for the steps.', 'Here is a test outline:\n' + _CODE + '\nIt checks every step with one sample value.'),
        ],
    },
    'de': {
        'done': [
            ('Füge die neuen Gemini-Modelle zur Konfiguration hinzu und starte die Tests.', 'Ich habe 4 Gemini-Modelle zur Anbieter-Konfiguration hinzugefügt und die Tests ausgeführt: 31 Tests bestehen. Die Änderungen stehen in providers/google.yml.'),
            ('Benenne den Projektordner um und korrigiere die Links.', 'Erledigt. Der Ordner heißt jetzt "Gartennotizen", und ich habe 7 defekte Links in der README korrigiert.'),
            ('Buche den günstigsten Termin beim Zahnarzt am Freitag.', 'Ich habe den Termin am Freitag um 09:30 gebucht, im günstigsten Tarif. Die Bestätigung liegt in deinem Kalender.'),
            ('Wandle meine Budget-Tabelle in CSV um.', 'Die Budget-Tabelle ist umgewandelt. Die CSV hat 128 Zeilen und 6 Spalten und liegt als budget.csv vor.'),
            ('Behebe den Login-Fehler auf der Einstellungsseite.', 'Behoben: Die Einstellungsseite meldet dich nach dem Speichern nicht mehr ab. Ich habe einen Regressionstest ergänzt, er läuft durch.'),
        ],
        'partial': [
            ('Migriere alle 5 Dienste auf die neue Datenbank.', 'Ich habe 3 von 5 Diensten migriert (Abrechnung, Suche, Mail). Die übrigen zwei scheitern, weil ihr Schema einen Spaltentyp nutzt, den die neue Datenbank nicht kennt.'),
            ('Aktualisiere die Abhängigkeiten und führe die Prüfungen aus.', 'Die Abhängigkeiten sind aktualisiert und der Build läuft. Die Lint-Prüfung meldet noch 2 Warnungen, die nichts damit zu tun haben.'),
            ('Plane die Reise und buche das Hotel.', 'Die Route für 5 Tage steht. Das Hotel konnte ich nicht buchen, weil die Seite den Zahlungsschritt abgelehnt hat; es ist also noch nichts gebucht.'),
            ('Bereinige die Daten und trainiere das Modell.', 'Die Daten sind bereinigt: 412 doppelte Zeilen entfernt. Das Training hat nicht gestartet, weil das GPU-Kontingent aufgebraucht ist.'),
        ],
        'question': [
            ('Welche Datenbank soll ich nehmen?', 'Beide würden funktionieren. Erwartest du mehr als ein paar tausend Schreibvorgänge pro Sekunde?'),
            ('Hilf mir beim Planen des Gartens.', 'Ich kann die Beete gleich skizzieren. Möchtest du Gemüse, Blumen oder beides?'),
            ('Schreibe mein Anschreiben neu.', 'Gern. Soll der Ton förmlich oder eher locker sein?'),
            ('Plane das Teammeeting.', 'Dienstag und Donnerstag sind beide frei. Welcher Tag passt dir besser?'),
        ],
        'long_question': [
            ('Vergleiche die beiden Heizungsoptionen.', _BULK['de'] * 3 + 'Welche der beiden soll ich im Detail durchrechnen?'),
            ('Prüfe den Vertrag und sag mir, was zu tun ist.', _BULK['de'] * 4 + 'Soll ich jetzt den Gegenvorschlag entwerfen?'),
            ('Erkläre meine Möglichkeiten beim Kredit.', _BULK['de'] * 3 + 'Soll ich für die Rechnung einen festen oder variablen Zins annehmen?'),
            ('Hilf mir bei der Laptop-Wahl.', _BULK['de'] * 3 + 'Wie hoch ist dein Budget?'),
        ],
        'info': [
            ('Wie funktioniert TLS?', 'TLS baut in einem Handshake einen verschlüsselten Kanal auf: Der Server weist sich per Zertifikat aus, beide Seiten einigen sich auf Schlüssel, danach wird der Verkehr schnell symmetrisch verschlüsselt.'),
            ('Was ist die Hauptstadt von Australien?', 'Die Hauptstadt von Australien ist Canberra, nicht Sydney. Sie wurde 1913 als Planstadt gegründet.'),
            ('Erkläre den Unterschied zwischen RAM und Speicher.', 'RAM ist schneller, flüchtiger Speicher für laufende Programme. Der Datenspeicher behält Daten dauerhaft, ist aber langsamer. Ein Computer braucht beides.'),
            ('Warum ist der Himmel blau?', 'Luftmoleküle streuen kurzwelliges blaues Sonnenlicht stärker als langwelliges rotes, daher erreicht gestreutes Blau dein Auge aus allen Richtungen.'),
        ],
        'code': [
            ('Zeige mir Hilfsfunktionen für die Schritte.', 'Hier sind die Hilfsfunktionen:\n' + _CODE + '\nJede addiert ihre eigene Schrittnummer zum Wert.'),
            ('Schreibe einen Parser für die Konfiguration.', 'Hier ein Parser-Entwurf:\n' + _CODE + '\nDie Schritte sind klein gehalten, damit du sie einzeln testen kannst.'),
            ('Gib mir Beispielcode für die Pipeline.', _CODE + '\nDas ist die ganze Pipeline; führe die Schritte der Reihe nach aus.'),
            ('Skizziere das Datenmodell.', 'Eine erste Skizze des Datenmodells:\n' + _CODE + '\nDie Namen können wir später verfeinern.'),
        ],
    },
    'es': {
        'done': [('Añade los nuevos modelos y ejecuta las pruebas.', 'He añadido 4 modelos a la configuración y he ejecutado las pruebas: pasan las 31. Los cambios están en providers/google.yml.'),
                 ('Renombra la carpeta del proyecto.', 'Hecho. La carpeta ahora se llama "notas-del-jardin" y he corregido 7 enlaces rotos del README.')],
        'partial': [('Migra los 5 servicios a la nueva base de datos.', 'He migrado 3 de los 5 servicios (facturación, búsqueda, correo). Los otros dos fallan porque usan un tipo de columna que la nueva base de datos no admite.'),
                    ('Planifica el viaje y reserva el hotel.', 'La ruta de 5 días está lista. No pude reservar el hotel porque la web rechazó el pago, así que todavía no hay nada reservado.')],
        'question': [('¿Qué base de datos uso?', 'Las dos servirían. ¿Esperas más de unos miles de escrituras por segundo?'),
                     ('Ayúdame con el jardín.', 'Puedo dibujar los bancales ahora. ¿Quieres verduras, flores o ambas?')],
        'long_question': [('Compara las dos opciones de calefacción.', _BULK['es'] * 3 + '¿Cuál de las dos quieres que calcule al detalle?'),
                          ('Revisa el contrato.', _BULK['es'] * 3 + '¿Quieres que redacte ya la contrapropuesta?')],
        'info': [('¿Cómo funciona TLS?', 'TLS crea un canal cifrado mediante un handshake: el servidor se identifica con un certificado, ambos acuerdan claves y después el tráfico se cifra con un cifrado simétrico rápido.'),
                 ('¿Por qué es azul el cielo?', 'Las moléculas del aire dispersan más la luz azul de onda corta que la roja de onda larga, por eso el azul dispersado llega a tus ojos desde todas partes.')],
        'code': [('Muéstrame funciones auxiliares.', 'Aquí están las funciones:\n' + _CODE + '\nCada una suma su propio número de paso al valor.'),
                 ('Dame código de ejemplo.', _CODE + '\nEs la canalización completa; ejecuta los pasos en orden.')],
    },
    'fr': {
        'done': [('Ajoute les nouveaux modèles et lance les tests.', "J'ai ajouté 4 modèles à la configuration et lancé les tests : les 31 passent. Les changements sont dans providers/google.yml."),
                 ('Renomme le dossier du projet.', 'Terminé. Le dossier s\'appelle maintenant "notes-du-jardin" et j\'ai corrigé 7 liens cassés du README.')],
        'partial': [('Migre les 5 services vers la nouvelle base.', "J'ai migré 3 services sur 5 (facturation, recherche, courrier). Les deux autres échouent car ils utilisent un type de colonne que la nouvelle base ne gère pas."),
                    ('Planifie le voyage et réserve l\'hôtel.', "L'itinéraire de 5 jours est prêt. Je n'ai pas pu réserver l'hôtel car le site a refusé le paiement ; rien n'est donc réservé.")],
        'question': [('Quelle base de données choisir ?', "Les deux conviendraient. Attends-tu plus de quelques milliers d'écritures par seconde ?"),
                     ('Aide-moi pour le jardin.', 'Je peux dessiner les parcelles maintenant. Veux-tu des légumes, des fleurs ou les deux ?')],
        'long_question': [('Compare les deux options de chauffage.', _BULK['fr'] * 3 + 'Laquelle des deux dois-je chiffrer en détail ?'),
                          ('Relis le contrat.', _BULK['fr'] * 3 + 'Veux-tu que je rédige tout de suite la contre-proposition ?')],
        'info': [('Comment fonctionne TLS ?', "TLS établit un canal chiffré lors d'une poignée de main : le serveur prouve son identité par un certificat, les deux parties conviennent de clés, puis le trafic est chiffré avec un chiffrement symétrique rapide."),
                 ('Pourquoi le ciel est-il bleu ?', "Les molécules de l'air diffusent davantage la lumière bleue, de courte longueur d'onde, que la rouge ; le bleu diffusé arrive donc à tes yeux de toutes les directions.")],
        'code': [('Montre-moi des fonctions utilitaires.', 'Voici les fonctions :\n' + _CODE + '\nChacune ajoute son propre numéro d\'étape à la valeur.'),
                 ("Donne-moi un exemple de code.", _CODE + '\nC\'est le pipeline complet ; exécute les étapes dans l\'ordre.')],
    },
    'pt': {
        'done': [('Adiciona os novos modelos e corre os testes.', 'Adicionei 4 modelos à configuração e corri os testes: os 31 passam. As alterações estão em providers/google.yml.')],
        'partial': [('Migra os 5 serviços para a nova base de dados.', 'Migrei 3 dos 5 serviços (faturação, pesquisa, correio). Os outros dois falham porque usam um tipo de coluna que a nova base não suporta.')],
        'question': [('Que base de dados devo usar?', 'Ambas servem. Esperas mais do que alguns milhares de escritas por segundo?')],
        'long_question': [('Compara as duas opções de aquecimento.', _BULK['pt'] * 3 + 'Qual das duas queres que calcule em detalhe?')],
        'info': [('Porque é que o céu é azul?', 'As moléculas do ar dispersam mais a luz azul, de onda curta, do que a vermelha; por isso o azul disperso chega aos teus olhos de todas as direções.')],
        'code': [('Mostra-me funções auxiliares.', 'Aqui estão as funções:\n' + _CODE + '\nCada uma soma o seu número de passo ao valor.')],
    },
    'ja': {
        'done': [('新しいモデルを設定に追加してテストを実行して。', '新しいGeminiモデルを4つ設定に追加し、テストを実行しました。31件すべて成功です。変更はproviders/google.ymlにあります。')],
        'partial': [('5つのサービスを新しいデータベースに移行して。', '5つのうち3つのサービス（請求、検索、メール）を移行しました。残りの2つは、新しいデータベースが対応していない列の型を使っているため失敗しました。')],
        'question': [('どのデータベースを使うべき？', 'どちらも使えます。1秒あたり数千件以上の書き込みを想定していますか？')],
        'long_question': [('二つの暖房案を比較して。', _BULK['ja'] * 3 + 'どちらを詳しく見積もりましょうか？')],
        'info': [('空はなぜ青いの？', '空気の分子は波長の短い青い光を赤い光より強く散乱させるため、散乱した青い光があらゆる方向から目に届きます。')],
        'code': [('補助関数を見せて。', '補助関数は次のとおりです。\n' + _CODE + '\nそれぞれが自分のステップ番号を値に足します。')],
    },
}


def _build() -> tuple[NotificationCase, ...]:
    cases = []
    for language, categories in _TEXT.items():
        for category, items in categories.items():
            for number, (user, assistant) in enumerate(items, 1):
                cases.append(NotificationCase(
                    id=f'synthetic-{language}-{category}-{number}', language=language, user=user,
                    assistant=assistant, required=(), expected=_EXPECTED[category]))
    return tuple(cases)


CASES = _build()
CASE_BY_ID = {case.id: case for case in CASES}
