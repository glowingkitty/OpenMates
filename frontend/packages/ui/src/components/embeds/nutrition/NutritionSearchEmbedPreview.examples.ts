/**
 * App-store examples for the nutrition search_recipes skill.
 *
 * Real REWE recipe fixtures. The shape matches the live REWE provider
 * response so preview + fullscreen exercise images, source links,
 * ingredients, instructions, and nutrition sections. A "Sample data" banner
 * is shown at the top of the fullscreen via the is_store_example flag set by
 * SkillExamplesSection.
 */

export interface NutritionSearchStoreExample {
  id: string;
  query: string;
  query_translation_key?: string;
  provider?: string;
  status: 'finished';
  results: Array<Record<string, unknown>>;
}

const penneSpinachCasserole = {
  "type": "recipe",
  "uid": "rewe-penne-spinat-auflauf",
  "title": "Penne-Spinat-Auflauf",
  "description": "Mit diesem leckeren Penne-Spinat-Auflauf wirst du ganz sicher nicht auflaufen. Unser REWE Rezept ist einfach Feta-tastisch!",
  "image_url": "https://c.rewe-static.de/36085419/1/36085419.png?impolicy=rds&im=Resize,width=740",
  "recipe_url": "https://www.rewe.de/rezepte/penne-spinat-auflauf/",
  "total_time_minutes": 55,
  "difficulty": "einfach",
  "rating": 4.3,
  "rating_count": 78,
  "servings": 4,
  "dietary_tags": ["Vegetarisch"],
  "ingredients": [
    { "amount": "900", "unit": "g", "name": "Rahmspinat" },
    { "amount": "500", "unit": "g", "name": "Penne" },
    { "amount": "", "unit": "", "name": "Salz" },
    { "amount": "1", "unit": "EL", "name": "Öl" },
    { "amount": "2", "unit": "", "name": "rote Spitzpaprika" },
    { "amount": "200", "unit": "g", "name": "Feta" },
    { "amount": "4", "unit": "", "name": "Eier (Größe M)" },
    { "amount": "2", "unit": "", "name": "Knoblauchzehen" },
    { "amount": "", "unit": "", "name": "Pfeffer" }
  ],
  "instructions": [
    { "step": 1, "text": "Spinat auftauen lassen. Penne in kochendem Salzwasser nach Packungsanweisung al dente kochen. Backofen auf 200 °C Ober- und Unterhitze vorheizen. Eine Auflaufform mit 1 EL Öl fetten." },
    { "step": 2, "text": "Paprika waschen, Stiel und Kerne entfernen. Paprika in Ringe schneiden. Feta würfeln." },
    { "step": 3, "text": "Eier verquirlen und unter den aufgetauten Spinat rühren. Knoblauch abziehen und dazu pressen. Mit Salz und Pfeffer würzen." },
    { "step": 4, "text": "Nudeln abgießen und gut abtropfen lassen, unter den Spinat mischen und in die Auflaufform geben. Paprikaringe und Fetawürfel darauf verteilen und im heißen Ofen 20-25 Minuten backen." }
  ],
  "nutrition": {
    "calories_kcal": 821,
    "protein_g": 37.8,
    "fat_g": 28.6,
    "carbs_g": 107
  }
};

const potatoCauliflowerCasserole = {
  "type": "recipe",
  "uid": "rewe-kartoffel-blumenkohl-hack-auflauf",
  "title": "Kartoffel-Blumenkohl-Hack-Auflauf",
  "description": "Der Kartoffel-Blumenkohl-Hackauflauf unter den REWE Rezepten überzeugt dich mit Aussehen, Geschmack und Nährwerten. Am besten klappt er mit festkochenden Kartoffeln.",
  "image_url": "https://c.rewe-static.de/30231160/8/30231160.png?impolicy=rds&im=Resize,width=740",
  "recipe_url": "https://www.rewe.de/rezepte/kartoffel-blumenkohl-hack-auflauf/",
  "total_time_minutes": 105,
  "difficulty": "einfach",
  "rating": 3.8,
  "rating_count": 903,
  "servings": 4,
  "dietary_tags": [],
  "ingredients": [
    { "amount": "800", "unit": "g", "name": "Kartoffeln" },
    { "amount": "1", "unit": "", "name": "Blumenkohl (ca. 1 kg)" },
    { "amount": "200", "unit": "g", "name": "Gouda" },
    { "amount": "1", "unit": "", "name": "Zwiebel" },
    { "amount": "3", "unit": "EL", "name": "Butter" },
    { "amount": "4", "unit": "EL", "name": "Weizenmehl Type 405" },
    { "amount": "200", "unit": "ml", "name": "Gemüsebrühe" },
    { "amount": "500", "unit": "ml", "name": "Milch" },
    { "amount": "", "unit": "", "name": "Salz" },
    { "amount": "", "unit": "", "name": "Pfeffer" },
    { "amount": "", "unit": "", "name": "Muskat" },
    { "amount": "400", "unit": "g", "name": "gemischtes Hackfleisch" }
  ],
  "instructions": [
    { "step": 1, "text": "Kartoffeln schälen, in dünne Scheiben schneiden oder raspeln. Blumenkohl in kleine Röschen aufteilen und waschen. Käse reiben." },
    { "step": 2, "text": "Zwiebel schälen und würfeln. Hälfte der Butter in einem Topf schmelzen. Mehl darin anschwitzen und mit Gemüsebrühe und Milch aufgießen. Unter Rühren aufkochen lassen und ca. 10 Minuten köcheln lassen. Dabei immer wieder umrühren. 100 g Käse in der Soße schmelzen lassen. Mit Salz, Pfeffer und Muskat abschmecken." },
    { "step": 3, "text": "Den Backofen auf 180°C Ober-/Unterhitze vorheizen. Restliche Butter in einer Pfanne erhitzen. Zwiebeln darin glasig dünsten. Das Hack hinzugeben und krümelig braten. Mit Salz und Pfeffer würzen." },
    { "step": 4, "text": "Kartoffeln, Blumenkohl und Hack in einer mit Butter gefetteten Auflaufform verteilen. Mit der Bechamelsauce übergießen und mit dem restlichen Käse bestreuen. Ca. 50 Minuten backen und ggf. nach 20 Minuten mit Alufolie abdecken." }
  ],
  "nutrition": {
    "calories_kcal": 796,
    "protein_g": 44.3,
    "fat_g": 45.4,
    "carbs_g": 55.9
  }
};

const lowCarbVegetableCasserole = {
  "type": "recipe",
  "uid": "rewe-low-carb-auflauf-gemuese-quark",
  "title": "Low carb Auflauf mit Gemüse und Quark",
  "description": "Probiere unseren Low carb Auflauf mit Gemüse und Quark! Das leckere REWE Rezept wird mit Brokkoli, Zucchini, Paprika und Feta zubereitet.",
  "image_url": "https://c.rewe-static.de/34581736/2/34581736.png?impolicy=rds&im=Resize,width=740",
  "recipe_url": "https://www.rewe.de/rezepte/low-carb-auflauf-mit-gemuese-und-quark/",
  "total_time_minutes": 70,
  "difficulty": "einfach",
  "rating": 3.8,
  "rating_count": 361,
  "servings": 4,
  "dietary_tags": ["Vegetarisch", "Low Carb", "Kalorienarm"],
  "ingredients": [
    { "amount": "500", "unit": "g", "name": "Brokkoli" },
    { "amount": "1", "unit": "große", "name": "Zucchini" },
    { "amount": "2", "unit": "", "name": "Paprika" },
    { "amount": "1", "unit": "", "name": "Zwiebel" },
    { "amount": "2", "unit": "", "name": "Knoblauchzehen" },
    { "amount": "100", "unit": "g", "name": "Feta" },
    { "amount": "1", "unit": "EL", "name": "Rapsöl" },
    { "amount": "", "unit": "", "name": "Salz" },
    { "amount": "", "unit": "", "name": "Pfeffer" },
    { "amount": "", "unit": "", "name": "Paprikapulver" },
    { "amount": "2", "unit": "", "name": "Eier" },
    { "amount": "500", "unit": "g", "name": "Magerquark" },
    { "amount": "4", "unit": "EL", "name": "Milch" },
    { "amount": "2", "unit": "EL", "name": "Grieß" },
    { "amount": "1", "unit": "Kugel", "name": "Mozzarella" }
  ],
  "instructions": [
    { "step": 1, "text": "Den Backofen auf 175 °C Umluft vorheizen. Brokkoli putzen und kleine Röschen schneiden." },
    { "step": 2, "text": "Zucchini waschen und in Würfel schneiden. Paprika waschen, Kerne entfernen und ebenfalls in Würfel schneiden." },
    { "step": 3, "text": "Zwiebel und Knoblauch schälen und fein hacken. Den Feta zerbröseln." },
    { "step": 4, "text": "Öl in einer Pfanne erhitzen und Zwiebel und Knoblauch kurz anbraten." },
    { "step": 5, "text": "Zucchini und Paprika zugeben und mitbraten. Zum Schluss den Brokkoli zufügen und einige Minuten mitgaren." },
    { "step": 6, "text": "Mit Salz, Pfeffer und Paprikapulver würzen, den Feta zufügen und alles auf dem Boden einer gefetteten Auflaufform verteilen." },
    { "step": 7, "text": "Die Eier trennen und das Eiweiß steif schlagen. Das Eigelb mit Quark, Milch und dem Grieß verrühren und mit Salz und Pfeffer würzen." },
    { "step": 8, "text": "Den Eischnee unterheben und die Ei-Quark-Masse auf dem Gemüse verteilen." },
    { "step": 9, "text": "Den Mozzarella in feine Scheiben schneiden, auf dem Auflauf verteilen und im vorgeheizten Backofen etwa 35 bis 40 Minuten überbacken." }
  ],
  "nutrition": {
    "calories_kcal": 358,
    "protein_g": 35.5,
    "fat_g": 14.1,
    "carbs_g": 23.3
  }
};

const examples: NutritionSearchStoreExample[] = [
  {
    "id": "store-example-nutrition-search-recipes-1",
    "query": "Vegetarische Pasta",
    "query_translation_key": "settings.app_store_examples.nutrition.search_recipes.1",
    "provider": "Sample Data",
    "status": "finished",
    "results": [penneSpinachCasserole, lowCarbVegetableCasserole, potatoCauliflowerCasserole]
  },
  {
    "id": "store-example-nutrition-search-recipes-2",
    "query": "Einfache Auflauf-Rezepte",
    "query_translation_key": "settings.app_store_examples.nutrition.search_recipes.2",
    "provider": "Sample Data",
    "status": "finished",
    "results": [potatoCauliflowerCasserole, penneSpinachCasserole, lowCarbVegetableCasserole]
  },
  {
    "id": "store-example-nutrition-search-recipes-3",
    "query": "Low Carb Abendessen",
    "query_translation_key": "settings.app_store_examples.nutrition.search_recipes.3",
    "provider": "Sample Data",
    "status": "finished",
    "results": [lowCarbVegetableCasserole, penneSpinachCasserole, potatoCauliflowerCasserole]
  }
];

export default examples;
