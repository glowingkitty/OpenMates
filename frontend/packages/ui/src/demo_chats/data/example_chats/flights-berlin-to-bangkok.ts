// frontend/packages/ui/src/demo_chats/data/example_chats/flights-berlin-to-bangkok.ts
//
// Example chat: Flights from Berlin to Bangkok
// Extracted from shared chat 3fb44cd4-61bb-48ad-a2fd-2d4728fcf95a
//
// A real conversation showcasing the travel flight search skill,
// comparing options from Qatar Airways, Turkish Airlines, Air France, and KLM.

import type { ExampleChat } from "../../types";

export const flightsBerlinBangkokChat: ExampleChat = {
  chat_id: "example-flights-berlin-bangkok",
  slug: "flights-berlin-to-bangkok",
  title: "example_chats.flights_berlin_bangkok.title",
  summary: "example_chats.flights_berlin_bangkok.summary",
  icon: "plane",
  category: "general_knowledge",
  keywords: [
    "flights Berlin Bangkok", "Berlin to Bangkok", "flight search",
    "Qatar Airways", "Turkish Airlines", "Air France", "KLM",
    "cheap flights Europe Asia", "one-way flights", "flight comparison",
    "travel booking", "airline tickets"
  ],
  follow_up_suggestions: [
    "example_chats.flights_berlin_bangkok.follow_up_1",
    "example_chats.flights_berlin_bangkok.follow_up_2",
    "example_chats.flights_berlin_bangkok.follow_up_3",
    "example_chats.flights_berlin_bangkok.follow_up_4",
    "example_chats.flights_berlin_bangkok.follow_up_5",
    "example_chats.flights_berlin_bangkok.follow_up_6",
  ],
  messages: [
    {
      id: "4728fcf95a-8de6a30d-6739-418a-ba3d-05891d471e7a",
      role: "user",
      content: "example_chats.flights_berlin_bangkok.user_message_1",
      created_at: 1774982436,
      category: "general_knowledge",
    },
    {
      id: "ab7d28d8-4481-4a59-ab9e-3ea5ae199246",
      role: "assistant",
      content: "example_chats.flights_berlin_bangkok.assistant_message_1",
      created_at: 1774982441,
      category: "general_knowledge",
      model_name: "Gemini 3 Flash",
    },
  ],
  embeds: [
    {
      embed_id: "2f88b2a0-4b85-4ac4-9200-74dccbb14823",
      type: "app_skill_use",
      content: `app_id: travel\nskill_id: search_connections\nresult_count: 5\nembed_ids: c0328462-5112-4ef2-ac54-3e359f1b625e|3159a788-4f2e-4951-b165-dd9ef253cf8f|a79e18e2-a4a3-4331-aa8e-3792fda0d053|fde6eba7-280f-4672-aafb-834051fb14d8|220ff6a9-7ead-415a-9055-a84436b907d9\nstatus: finished\nlegs[1]{destination,date,origin}:\n  Bangkok,2026-04-14,Berlin`,
      parent_embed_id: null,
      embed_ids: [
        "c0328462-5112-4ef2-ac54-3e359f1b625e",
        "3159a788-4f2e-4951-b165-dd9ef253cf8f",
        "a79e18e2-a4a3-4331-aa8e-3792fda0d053",
        "fde6eba7-280f-4672-aafb-834051fb14d8",
        "220ff6a9-7ead-415a-9055-a84436b907d9",
      ],
    },
    {
      embed_id: "c0328462-5112-4ef2-ac54-3e359f1b625e",
      type: "connection",
      content: `type: connection\ntransport_method: airplane\ntrip_type: one_way\ntotal_price: "636"\ncurrency: EUR\nbookable_seats: null\nlast_ticketing_date: null\nlegs[1]:\n  - leg_index: 0\n    origin: Berlin (BER)\n    destination: Bangkok (BKK)\n    departure: "2026-04-14 10:00"\n    arrival: "2026-04-15 06:20"\n    duration: 15h 20m\n    stops: 1\n    segments[2]{carrier,carrier_code,number,departure_station,departure_time,departure_latitude,departure_longitude,arrival_station,arrival_time,arrival_latitude,arrival_longitude,duration,departure_country_code,arrival_country_code,departure_is_daytime,arrival_is_daytime,airplane,airline_logo,legroom,travel_class,extensions,often_delayed}:\n      Qatar Airways,QR,QR 80,BER,"2026-04-14 10:00",52.362877,13.503722,DOH,"2026-04-14 17:05",25.272524,51.608604,6h 5m,DE,QA,true,true,Boeing 787,"https://www.gstatic.com/flights/airline_logos/70px/QR.png",31 in,Economy,"Average legroom (31 in)|Wi-Fi for a fee|In-seat power & USB outlets|On-demand video|Carbon emissions estimate: 264 kg",null\n      Qatar Airways,QR,QR 838,DOH,"2026-04-14 19:35",25.272524,51.608604,BKK,"2026-04-15 06:20",13.6811,100.7472,6h 45m,QA,TH,false,true,Boeing 777,"https://www.gstatic.com/flights/airline_logos/70px/QR.png",31 in,Economy,"Average legroom (31 in)|Free Wi-Fi|In-seat power & USB outlets|On-demand video|Carbon emissions estimate: 401 kg",null\n    layovers[1]{airport,airport_code,duration,duration_minutes,overnight}:\n      Hamad International Airport,DOH,2h 30m,150,null\nhash: 8a33802a95606006\norigin: Berlin (BER)\ndestination: Bangkok (BKK)\ndeparture: "2026-04-14 10:00"\narrival: "2026-04-15 06:20"\nduration: 15h 20m\nstops: 1\ncarriers: Qatar Airways\ncarrier_codes: QR\nbooking_token: WyJDalJJTnpCMmIxWjBOMVZ4YWtGQlEzcDNOWGRDUnkwdExTMHRMUzB0ZVdsaVozUXhOa0ZCUVVGQlIyNU5SbE4zU21SSlJuRkJFZ3BSVWpnd2ZGRlNPRE00R2dzSXNQQURFQUlhQTBWVlVqZ2NjSk85QkE9PSIsW1siQkVSIiwiMjAyNi0wNC0xNCIsIkRPSCIsbnVsbCwiUVIiLCI4MCJdLFsiRE9IIiwiMjAyNi0wNC0xNCIsIkJLSyIsbnVsbCwiUVIiLCI4MzgiXV1d\nbooking_context_departure_id: BER\nbooking_context_arrival_id: BKK\nbooking_context_outbound_date: 2026-04-14\nbooking_context_type: "2"\nbooking_context_currency: EUR\nbooking_context_gl: de\nbooking_context_adults: "1"\nbooking_context_travel_class: "1"\nairline_logo: "https://www.gstatic.com/flights/airline_logos/70px/QR.png"\nco2_kg: 665\nco2_typical_kg: 635\nco2_difference_percent: 5\nembed_ref: qatar-2026-OlW\napp_id: travel\nskill_id: search_connections`,
      parent_embed_id: "2f88b2a0-4b85-4ac4-9200-74dccbb14823",
      embed_ids: null,
    },
    {
      embed_id: "3159a788-4f2e-4951-b165-dd9ef253cf8f",
      type: "connection",
      content: `type: connection\ntransport_method: airplane\ntrip_type: one_way\ntotal_price: "636"\ncurrency: EUR\nbookable_seats: null\nlast_ticketing_date: null\nlegs[1]:\n  - leg_index: 0\n    origin: Berlin (BER)\n    destination: Bangkok (BKK)\n    departure: "2026-04-14 16:45"\n    arrival: "2026-04-15 12:20"\n    duration: 14h 35m\n    stops: 1\n    segments[2]{carrier,carrier_code,number,departure_station,departure_time,departure_latitude,departure_longitude,arrival_station,arrival_time,arrival_latitude,arrival_longitude,duration,departure_country_code,arrival_country_code,departure_is_daytime,arrival_is_daytime,airplane,airline_logo,legroom,travel_class,extensions,often_delayed}:\n      Qatar Airways,QR,QR 82,BER,"2026-04-14 16:45",52.362877,13.503722,DOH,"2026-04-14 23:40",25.272524,51.608604,5h 55m,DE,QA,true,false,Boeing 787,"https://www.gstatic.com/flights/airline_logos/70px/QR.png",31 in,Economy,"Average legroom (31 in)|Wi-Fi for a fee|In-seat power & USB outlets|On-demand video|Carbon emissions estimate: 264 kg",null\n      Qatar Airways,QR,QR 828,DOH,"2026-04-15 01:35",25.272524,51.608604,BKK,"2026-04-15 12:20",13.6811,100.7472,6h 45m,QA,TH,false,true,Boeing 777,"https://www.gstatic.com/flights/airline_logos/70px/QR.png",31 in,Economy,"Average legroom (31 in)|Free Wi-Fi|In-seat power & USB outlets|On-demand video|Carbon emissions estimate: 401 kg",null\n    layovers[1]{airport,airport_code,duration,duration_minutes,overnight}:\n      Hamad International Airport,DOH,1h 55m,115,null\nhash: a9c12553c503adfa\norigin: Berlin (BER)\ndestination: Bangkok (BKK)\ndeparture: "2026-04-14 16:45"\narrival: "2026-04-15 12:20"\nduration: 14h 35m\nstops: 1\ncarriers: Qatar Airways\ncarrier_codes: QR\nbooking_token: WyJDalJJTnpCMmIxWjBOMVZ4YWtGQlEzcDNOWGRDUnkwdExTMHRMUzB0ZVdsaVozUXhOa0ZCUVVGQlIyNU5SbE4zU21SSlJuRkJFZ3BSVWpneWZGRlNPREk0R2dzSXNQQURFQUlhQTBWVlVqZ2NjSk85QkE9PSIsW1siQkVSIiwiMjAyNi0wNC0xNCIsIkRPSCIsbnVsbCwiUVIiLCI4MiJdLFsiRE9IIiwiMjAyNi0wNC0xNSIsIkJLSyIsbnVsbCwiUVIiLCI4MjgiXV1d\nbooking_context_departure_id: BER\nbooking_context_arrival_id: BKK\nbooking_context_outbound_date: 2026-04-14\nbooking_context_type: "2"\nbooking_context_currency: EUR\nbooking_context_gl: de\nbooking_context_adults: "1"\nbooking_context_travel_class: "1"\nairline_logo: "https://www.gstatic.com/flights/airline_logos/70px/QR.png"\nco2_kg: 665\nco2_typical_kg: 635\nco2_difference_percent: 5\nembed_ref: qatar-2026-X5r\napp_id: travel\nskill_id: search_connections`,
      parent_embed_id: "2f88b2a0-4b85-4ac4-9200-74dccbb14823",
      embed_ids: null,
    },
    {
      embed_id: "a79e18e2-a4a3-4331-aa8e-3792fda0d053",
      type: "connection",
      content: `type: connection\ntransport_method: airplane\ntrip_type: one_way\ntotal_price: "715"\ncurrency: EUR\nbookable_seats: null\nlast_ticketing_date: null\nlegs[1]:\n  - leg_index: 0\n    origin: Berlin (BER)\n    destination: Bangkok (BKK)\n    departure: "2026-04-14 12:50"\n    arrival: "2026-04-15 09:15"\n    duration: 15h 25m\n    stops: 1\n    segments[2]{carrier,carrier_code,number,departure_station,departure_time,departure_latitude,departure_longitude,arrival_station,arrival_time,arrival_latitude,arrival_longitude,duration,departure_country_code,arrival_country_code,departure_is_daytime,arrival_is_daytime,airplane,airline_logo,legroom,travel_class,extensions,often_delayed}:\n      Air France,AF,AF 1735,BER,"2026-04-14 12:50",52.362877,13.503722,CDG,"2026-04-14 14:40",49.012516,2.555752,1h 50m,DE,FR,true,true,Airbus A220-300 Passenger,"https://www.gstatic.com/flights/airline_logos/70px/AF.png",30 in,Economy,"Average legroom (30 in)|Wi-Fi for a fee|In-seat USB outlet|Carbon emissions estimate: 96 kg",null\n      Air France,AF,AF 198,CDG,"2026-04-14 16:45",49.012516,2.555752,BKK,"2026-04-15 09:15",13.6811,100.7472,11h 30m,FR,TH,true,true,Airbus A350,"https://www.gstatic.com/flights/airline_logos/70px/AF.png",31 in,Economy,"Average legroom (31 in)|Wi-Fi for a fee|In-seat USB outlet|On-demand video|Carbon emissions estimate: 532 kg",null\n    layovers[1]{airport,airport_code,duration,duration_minutes,overnight}:\n      Paris Charles de Gaulle Airport,CDG,2h 5m,125,null\nhash: ac9e531ddda4f53b\norigin: Berlin (BER)\ndestination: Bangkok (BKK)\ndeparture: "2026-04-14 12:50"\narrival: "2026-04-15 09:15"\nduration: 15h 25m\nstops: 1\ncarriers: Air France\ncarrier_codes: AF\nbooking_token: WyJDalJJTnpCMmIxWjBOMVZ4YWtGQlEzcDNOWGRDUnkwdExTMHRMUzB0ZVdsaVozUXhOa0ZCUVVGQlIyNU5SbE4zU21SSlJuRkJFZ3hCUmpFM016VjhRVVl4T1RnYUN3anpyUVFRQWhvRFJWVlNPQnh3bUlRRiIsW1siQkVSIiwiMjAyNi0wNC0xNCIsIkNERyIsbnVsbCwiQUYiLCIxNzM1Il0sWyJDREciLCIyMDI2LTA0LTE0IiwiQktLIixudWxsLCJBRiIsIjE5OCJdXV0=\nbooking_context_departure_id: BER\nbooking_context_arrival_id: BKK\nbooking_context_outbound_date: 2026-04-14\nbooking_context_type: "2"\nbooking_context_currency: EUR\nbooking_context_gl: de\nbooking_context_adults: "1"\nbooking_context_travel_class: "1"\nairline_logo: "https://www.gstatic.com/flights/airline_logos/70px/AF.png"\nco2_kg: 628\nco2_typical_kg: 635\nco2_difference_percent: -1\nembed_ref: air-2026-u4K\napp_id: travel\nskill_id: search_connections`,
      parent_embed_id: "2f88b2a0-4b85-4ac4-9200-74dccbb14823",
      embed_ids: null,
    },
    {
      embed_id: "fde6eba7-280f-4672-aafb-834051fb14d8",
      type: "connection",
      content: `type: connection\ntransport_method: airplane\ntrip_type: one_way\ntotal_price: "725"\ncurrency: EUR\nbookable_seats: null\nlast_ticketing_date: null\nlegs[1]:\n  - leg_index: 0\n    origin: Berlin (BER)\n    destination: Bangkok (BKK)\n    departure: "2026-04-14 14:15"\n    arrival: "2026-04-15 09:30"\n    duration: 14h 15m\n    stops: 1\n    segments[2]{carrier,carrier_code,number,departure_station,departure_time,departure_latitude,departure_longitude,arrival_station,arrival_time,arrival_latitude,arrival_longitude,duration,departure_country_code,arrival_country_code,departure_is_daytime,arrival_is_daytime,airplane,airline_logo,legroom,travel_class,extensions,often_delayed}:\n      KLM,KL,KL 1778,BER,"2026-04-14 14:15",52.362877,13.503722,AMS,"2026-04-14 15:35",52.308609,4.763889,1h 20m,DE,NL,true,true,Boeing 737,"https://www.gstatic.com/flights/airline_logos/70px/KL.png",30 in,Economy,"Average legroom (30 in)|Carbon emissions estimate: 73 kg",null\n      KLM,KL,KL 843,AMS,"2026-04-14 17:15",52.308609,4.763889,BKK,"2026-04-15 09:30",13.6811,100.7472,11h 15m,NL,TH,true,true,Boeing 777,"https://www.gstatic.com/flights/airline_logos/70px/KL.png",31 in,Economy,"Average legroom (31 in)|Wi-Fi for a fee|In-seat USB outlet|On-demand video|Carbon emissions estimate: 618 kg",null\n    layovers[1]{airport,airport_code,duration,duration_minutes,overnight}:\n      Amsterdam Airport Schiphol,AMS,1h 40m,100,null\nhash: 22d274202942f191\norigin: Berlin (BER)\ndestination: Bangkok (BKK)\ndeparture: "2026-04-14 14:15"\narrival: "2026-04-15 09:30"\nduration: 14h 15m\nstops: 1\ncarriers: KLM\ncarrier_codes: KL\nbooking_token: WyJDalJJTnpCMmIxWjBOMVZ4YWtGQlEzcDNOWGRDUnkwdExTMHRMUzB0ZVdsaVozUXhOa0ZCUVVGQlIyNU5SbE4zU21SSlJuRkJFZ3hMVERFM056aDhTMHc0TkRNYUN3alJ0UVFRQWhvRFJWVlNPQnh3ajQwRiIsW1siQkVSIiwiMjAyNi0wNC0xNCIsIkFNUyIsbnVsbCwiS0wiLCIxNzc4Il0sWyJBTVMiLCIyMDI2LTA0LTE0IiwiQktLIixudWxsLCJLTCIsIjg0MyJdXV0=\nbooking_context_departure_id: BER\nbooking_context_arrival_id: BKK\nbooking_context_outbound_date: 2026-04-14\nbooking_context_type: "2"\nbooking_context_currency: EUR\nbooking_context_gl: de\nbooking_context_adults: "1"\nbooking_context_travel_class: "1"\nairline_logo: "https://www.gstatic.com/flights/airline_logos/70px/KL.png"\nco2_kg: 693\nco2_typical_kg: 635\nco2_difference_percent: 9\nembed_ref: klm-2026-oxW\napp_id: travel\nskill_id: search_connections`,
      parent_embed_id: "2f88b2a0-4b85-4ac4-9200-74dccbb14823",
      embed_ids: null,
    },
    {
      embed_id: "220ff6a9-7ead-415a-9055-a84436b907d9",
      type: "connection",
      content: `type: connection\ntransport_method: airplane\ntrip_type: one_way\ntotal_price: "741"\ncurrency: EUR\nbookable_seats: null\nlast_ticketing_date: null\nlegs[1]:\n  - leg_index: 0\n    origin: Berlin (BER)\n    destination: Bangkok (BKK)\n    departure: "2026-04-14 10:40"\n    arrival: "2026-04-15 05:05"\n    duration: 13h 25m\n    stops: 1\n    segments[2]{carrier,carrier_code,number,departure_station,departure_time,departure_latitude,departure_longitude,arrival_station,arrival_time,arrival_latitude,arrival_longitude,duration,departure_country_code,arrival_country_code,departure_is_daytime,arrival_is_daytime,airplane,airline_logo,legroom,travel_class,extensions,often_delayed}:\n      Turkish Airlines,TK,TK 1722,BER,"2026-04-14 10:40",52.362877,13.503722,IST,"2026-04-14 14:40",41.270149,28.733362,3h,DE,TR,true,null,Airbus A330,"https://www.gstatic.com/flights/airline_logos/70px/TK.png",31 in,Economy,"Average legroom (31 in)|Wi-Fi for a fee|In-seat power & USB outlets|On-demand video|Carbon emissions estimate: 142 kg",null\n      Turkish Airlines,TK,TK 58,IST,"2026-04-14 15:50",41.270149,28.733362,BKK,"2026-04-15 05:05",13.6811,100.7472,9h 15m,TR,TH,null,false,Airbus A350,"https://www.gstatic.com/flights/airline_logos/70px/TK.png",31 in,Economy,"Average legroom (31 in)|Wi-Fi for a fee|In-seat USB outlet|On-demand video|Carbon emissions estimate: 480 kg",null\n    layovers[1]{airport,airport_code,duration,duration_minutes,overnight}:\n      Istanbul Airport,IST,1h 10m,70,null\nhash: a210b1d5ace160c2\norigin: Berlin (BER)\ndestination: Bangkok (BKK)\ndeparture: "2026-04-14 10:40"\narrival: "2026-04-15 05:05"\nduration: 13h 25m\nstops: 1\ncarriers: Turkish Airlines\ncarrier_codes: TK\nbooking_token: WyJDalJJTnpCMmIxWjBOMVZ4YWtGQlEzcDNOWGRDUnkwdExTMHRMUzB0ZVdsaVozUXhOa0ZCUVVGQlIyNU5SbE4zU21SSlJuRkJFZ3RVU3pFM01qSjhWRXMxT0JvTENPckNCQkFDR2dORlZWSTRISEN0bkFVPSIsW1siQkVSIiwiMjAyNi0wNC0xNCIsIklTVCIsbnVsbCwiVEsiLCIxNzIyIl0sWyJJU1QiLCIyMDI2LTA0LTE0IiwiQktLIixudWxsLCJUSyIsIjU4Il1dXQ==\nbooking_context_departure_id: BER\nbooking_context_arrival_id: BKK\nbooking_context_outbound_date: 2026-04-14\nbooking_context_type: "2"\nbooking_context_currency: EUR\nbooking_context_gl: de\nbooking_context_adults: "1"\nbooking_context_travel_class: "1"\nairline_logo: "https://www.gstatic.com/flights/airline_logos/70px/TK.png"\nco2_kg: 623\nco2_typical_kg: 635\nco2_difference_percent: -2\nembed_ref: turkish-2026-yrG\napp_id: travel\nskill_id: search_connections`,
      parent_embed_id: "2f88b2a0-4b85-4ac4-9200-74dccbb14823",
      embed_ids: null,
    },
    {
      embed_id: "4efde0ba-b891-4651-b00b-a7789f715c8c",
      type: "sheet",
      content: `type: sheet\napp_id: sheets\nskill_id: sheet\ntable: "| Airline | Departure | Duration | Price |\\n| :--- | :--- | :--- | :--- |\\n| Qatar Airways | 10:00 | 15h 20m | \u20ac636 |\\n| Qatar Airways | 16:45 | 14h 35m | \u20ac636 |\\n| Air France | 12:50 | 15h 25m | \u20ac715 |\\n| KLM | 14:15 | 14h 15m | \u20ac725 |\\n| Turkish Airlines | 10:40 | 13h 25m | \u20ac741 |"\ntitle: ""\nstatus: finished\nrow_count: 5\ncol_count: 4`,
      parent_embed_id: null,
      embed_ids: null,
    },
  ],
  metadata: {
    featured: true,
    order: 4,
  },
};
