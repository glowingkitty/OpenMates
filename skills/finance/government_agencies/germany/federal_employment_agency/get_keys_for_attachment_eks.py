################

# Default Imports

################
import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)
from server import *

################

# get the data for the Attachment for self-employment income (Anlage EKS) for the German Federal Employment Agency (Bundesagentur für Arbeit/Jobcenter)

# https://www.arbeitsagentur.de/datei/anlageeks_ba013054.pdf


def get_keys_for_attachment_eks() -> dict:
    try:
        add_to_log(module_name="Federal Employment Agency | Germany | Attachment EKS | Get EKS keys", color="yellow", state="start")
        add_to_log("Getting the keys for the 'Attachment for self-employment income' (Anlage EKS) ...")

        # accounting types from:
        # ../my_profile/systemprompts/special_usecases/bank_transactions_processing/sevdesk_germany/extract_invoice_data.md
        key_descriptions = {
            "A1":       {"description":"Betriebseinnahmen",                                                                                                 "accounting_types":[26,27,31,84,39,108,40,38,36,41]},
            "A2":       {"description":"Privatentnahmen von Waren",                                                                                         "accounting_types":[]},
            "A3":       {"description":"sonstige betriebliche Einnahmen (zum Beispiel auch kostenfrei auf Dauer überlassene Produkte)",                     "accounting_types":[]},
            "A4":       {"description":"Zuwendung von Dritten",                                                                                             "accounting_types":[]},
            "A5":       {"description":"vereinnahmte Umsatzsteuer",                                                                                         "accounting_types":[25]},
            "A6":       {"description":"Umsatzsteuer auf Privatentnahmen von Waren",                                                                        "accounting_types":[]},
            "A7":       {"description":"vom Finanzamt erstattete Umsatzsteuer",                                                                             "accounting_types":[]}, # should also be 84, but collides with A1
            
            "B1":       {"description":"Wareneinkauf",                                                                                                      "accounting_types":[19,18]},
            "B2 a)":    {"description":"Personalkosten (einschließlich Sozialversicherungsbeiträge) -> Vollzeitbeschäftigte",                               "accounting_types":[25225,25226,57,60]},
            "B2 b)":    {"description":"Personalkosten (einschließlich Sozialversicherungsbeiträge) -> Teilzeitbeschäftigte",                               "accounting_types":[25224,46,49,56,58]},
            "B2 c)":    {"description":"Personalkosten (einschließlich Sozialversicherungsbeiträge) -> geringfügig Beschäftigte (520 Euro-Job)",            "accounting_types":[25228,59,25227]},
            "B2 d)":    {"description":"Personalkosten (einschließlich Sozialversicherungsbeiträge) -> mithelfende Familienangehörige",                     "accounting_types":[]},
            "B3":       {"description":"Raumkosten (einschließlich Nebenkosten und Energiekosten)",                                                         "accounting_types":[52,53,69,77]},
            "B4":       {"description":"betriebliche Versicherungen/ Beiträge",                                                                             "accounting_types":[92,93,94,95,96]},
            "B5.1 a)":  {"description":"Kraftfahrzeugkosten -> betriebliches Kraftfahrzeug -> Steuern",                                                     "accounting_types":[7]},
            "B5.1 b)":  {"description":"Kraftfahrzeugkosten -> betriebliches Kraftfahrzeug -> Versicherung",                                                "accounting_types":[8]},
            "B5.1 c)":  {"description":"Kraftfahrzeugkosten -> betriebliches Kraftfahrzeug -> laufende Betriebskosten",                                     "accounting_types":[5,11,65233,12,10]},
            "B5.1 d)":  {"description":"Kraftfahrzeugkosten -> betriebliches Kraftfahrzeug -> Reparaturen",                                                 "accounting_types":[6]},
            "B5.1 e)":  {"description":"Kraftfahrzeugkosten -> betriebliches Kraftfahrzeug -> abzüglich privat gefahrene km (0,10 Euro je gefahrenem km)",  "accounting_types":[]},
            "B5.2":     {"description":"Kraftfahrzeugkosten -> privates Kraftfahrzeug -> betriebliche Fahrten (0,10 Euro je gefahrenem km)",                "accounting_types":[25237]},
            "B6":       {"description":"Werbung",                                                                                                           "accounting_types":[101,102,103,100,20,110]},
            "B7 a)":    {"description":"Reisekosten -> Übernachtungskosten",                                                                                "accounting_types":[66,25235]},
            "B7 b)":    {"description":"Reisekosten -> Reisenebenkosten",                                                                                   "accounting_types":[1597,25234,9,43,63,25233,25236]},
            "B7 c)":    {"description":"Reisekosten -> öffentliche Verkehrsmittel",                                                                         "accounting_types":[62,64,65]},
            "B8":       {"description":"Investitionen",                                                                                                     "accounting_types":[2809,2811,2812]},
            "B9":       {"description":"Investitionen aus Zuwendungen Dritter",                                                                             "accounting_types":[662054]},
            "B10":      {"description":"Büromaterial einschließlich Porto",                                                                                 "accounting_types":[72,90]},
            "B11":      {"description":"Telefonkosten",                                                                                                     "accounting_types":[88]},
            "B12":      {"description":"Beratungskosten",                                                                                                   "accounting_types":[22,23,2816]},
            "B13":      {"description":"Fortbildungskosten",                                                                                                "accounting_types":[2821]},
            "B14 a)":   {"description":"sonstige Betriebsausgaben -> Reparatur Anlagevermögen",                                                             "accounting_types":[2822]},
            "B14 b)":   {"description":"sonstige Betriebsausgaben -> Miete Einrichtung",                                                                    "accounting_types":[65232]},
            "B14 c)":   {"description":"sonstige Betriebsausgaben -> Nebenkosten des Geldverkehrs",                                                         "accounting_types":[74,79,82,81,73]},
            "B14 d)":   {"description":"sonstige Betriebsausgaben -> betriebliche Abfallbeseitigung",                                                       "accounting_types":[54]},
            "B14 e)":   {"description":"sonstige Betriebsausgaben -> Sonstiges (Software Miete / Lizenzen / Leasing)",                                      "accounting_types":[2819, 51]},
            "B14 f)":   {"description":"sonstige Betriebsausgaben -> Sonstiges (Web hosting / Domains / Internet)",                                         "accounting_types":[2820,89]},
            "B14 g)":   {"description":"sonstige Betriebsausgaben -> Sonstiges (Kleingeräte)",                                                              "accounting_types":[68]},
            "B14 h)":   {"description":"sonstige Betriebsausgaben -> Sonstiges (Spenden)",                                                                  "accounting_types":[104]},
            "B14 i)":   {"description":"sonstige Betriebsausgaben -> Sonstiges (Transportkosten / Sonstiges)",                                              "accounting_types":[78,65231,71,107]},
            "B15":      {"description":"Schuldzinsen aus Anlagevermögen",                                                                                   "accounting_types":[15,16]},
            "B16":      {"description":"Tilgung bestehender betrieblicher Darlehen",                                                                        "accounting_types":[14]},
            "B17":      {"description":"gezahlte Vorsteuer",                                                                                                "accounting_types":[3,106]},
            "B18":      {"description":"an das Finanzamt gezahlte Umsatzsteuer",                                                                            "accounting_types":[85,86]}
        }

        return key_descriptions

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to get the keys for the 'attachment for self-employment income' (Anlage EKS)", traceback=traceback.format_exc())
        return None

if __name__ == "__main__":
    keys = get_keys_for_attachment_eks()
    print(keys)