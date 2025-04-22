# backend/core/api/app/services/invoiceninja/countries.py
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Country ID mapping based on Invoice Ninja documentation (using 2-letter code)
COUNTRY_CODE_TO_ID_MAP = {
    "AF": 4,    # Afghanistan
    "AL": 8,    # Albania
    "AQ": 10,   # Antarctica
    "DZ": 12,   # Algeria
    "AS": 16,   # American Samoa
    "AD": 20,   # Andorra
    "AO": 24,   # Angola
    "AG": 28,   # Antigua and Barbuda
    "AZ": 31,   # Azerbaijan
    "AR": 32,   # Argentina
    "AU": 36,   # Australia
    "AT": 40,   # Austria
    "BS": 44,   # Bahamas
    "BH": 48,   # Bahrain
    "BD": 50,   # Bangladesh
    "AM": 51,   # Armenia
    "BB": 52,   # Barbados
    "BE": 56,   # Belgium
    "BM": 60,   # Bermuda
    "BT": 64,   # Bhutan
    "BO": 68,   # Bolivia, Plurinational State of
    "BA": 70,   # Bosnia and Herzegovina
    "BW": 72,   # Botswana
    "BV": 74,   # Bouvet Island
    "BR": 76,   # Brazil
    "BZ": 84,   # Belize
    "IO": 86,   # British Indian Ocean Territory
    "SB": 90,   # Solomon Islands
    "VG": 92,   # Virgin Islands, British
    "BN": 96,   # Brunei Darussalam
    "BG": 100,  # Bulgaria
    "MM": 104,  # Myanmar
    "BI": 108,  # Burundi
    "BY": 112,  # Belarus
    "KH": 116,  # Cambodia
    "CM": 120,  # Cameroon
    "CA": 124,  # Canada
    "CV": 132,  # Cape Verde
    "KY": 136,  # Cayman Islands
    "CF": 140,  # Central African Republic
    "LK": 144,  # Sri Lanka
    "TD": 148,  # Chad
    "CL": 152,  # Chile
    "CN": 156,  # China
    "TW": 158,  # Taiwan
    "CX": 162,  # Christmas Island
    "CC": 166,  # Cocos (Keeling) Islands
    "CO": 170,  # Colombia
    "KM": 174,  # Comoros
    "YT": 175,  # Mayotte
    "CG": 178,  # Congo
    "CD": 180,  # Congo, the Democratic Republic of the
    "CK": 184,  # Cook Islands
    "CR": 188,  # Costa Rica
    "HR": 191,  # Croatia
    "CU": 192,  # Cuba
    "CY": 196,  # Cyprus
    "CZ": 203,  # Czech Republic
    "BJ": 204,  # Benin
    "DK": 208,  # Denmark
    "DM": 212,  # Dominica
    "DO": 214,  # Dominican Republic
    "EC": 218,  # Ecuador
    "SV": 222,  # El Salvador
    "GQ": 226,  # Equatorial Guinea
    "ET": 231,  # Ethiopia
    "ER": 232,  # Eritrea
    "EE": 233,  # Estonia
    "FO": 234,  # Faroe Islands
    "FK": 238,  # Falkland Islands (Malvinas)
    "GS": 239,  # South Georgia and the South Sandwich Islands
    "FJ": 242,  # Fiji
    "FI": 246,  # Finland
    "AX": 248,  # Åland Islands
    "FR": 250,  # France
    "GF": 254,  # French Guiana
    "PF": 258,  # French Polynesia
    "TF": 260,  # French Southern Territories
    "DJ": 262,  # Djibouti
    "GA": 266,  # Gabon
    "GE": 268,  # Georgia
    "GM": 270,  # Gambia
    "PS": 275,  # Palestine
    "DE": 276,  # Germany
    "GH": 288,  # Ghana
    "GI": 292,  # Gibraltar
    "KI": 296,  # Kiribati
    "GR": 300,  # Greece
    "GL": 304,  # Greenland
    "GD": 308,  # Grenada
    "GP": 312,  # Guadeloupe
    "GU": 316,  # Guam
    "GT": 320,  # Guatemala
    "GN": 324,  # Guinea
    "GY": 328,  # Guyana
    "HT": 332,  # Haiti
    "HM": 334,  # Heard Island and McDonald Islands
    "VA": 336,  # Holy See (Vatican City State)
    "HN": 340,  # Honduras
    "HK": 344,  # Hong Kong
    "HU": 348,  # Hungary
    "IS": 352,  # Iceland
    "IN": 356,  # India
    "ID": 360,  # Indonesia
    "IR": 364,  # Iran, Islamic Republic of
    "IQ": 368,  # Iraq
    "IE": 372,  # Ireland
    "IL": 376,  # Israel
    "IT": 380,  # Italy
    "CI": 384,  # Côte d'Ivoire
    "JM": 388,  # Jamaica
    "JP": 392,  # Japan
    "KZ": 398,  # Kazakhstan
    "JO": 400,  # Jordan
    "KE": 404,  # Kenya
    "KP": 408,  # Korea, Democratic People's Republic of
    "KR": 410,  # Korea, Republic of
    "KW": 414,  # Kuwait
    "KG": 417,  # Kyrgyzstan
    "LA": 418,  # Lao People's Democratic Republic
    "LB": 422,  # Lebanon
    "LS": 426,  # Lesotho
    "LV": 428,  # Latvia
    "LR": 430,  # Liberia
    "LY": 434,  # Libya
    "LI": 438,  # Liechtenstein
    "LT": 440,  # Lithuania
    "LU": 442,  # Luxembourg
    "MO": 446,  # Macao
    "MG": 450,  # Madagascar
    "MW": 454,  # Malawi
    "MY": 458,  # Malaysia
    "MV": 462,  # Maldives
    "ML": 466,  # Mali
    "MT": 470,  # Malta
    "MQ": 474,  # Martinique
    "MR": 478,  # Mauritania
    "MU": 480,  # Mauritius
    "MX": 484,  # Mexico
    "MC": 492,  # Monaco
    "MN": 496,  # Mongolia
    "MD": 498,  # Moldova, Republic of
    "ME": 499,  # Montenegro
    "MS": 500,  # Montserrat
    "MA": 504,  # Morocco
    "MZ": 508,  # Mozambique
    "OM": 512,  # Oman
    "NA": 516,  # Namibia
    "NR": 520,  # Nauru
    "NP": 524,  # Nepal
    "NL": 528,  # Netherlands
    "CW": 531,  # Curaçao
    "AW": 533,  # Aruba
    "SX": 534,  # Sint Maarten (Dutch part)
    "BQ": 535,  # Bonaire, Sint Eustatius and Saba
    "NC": 540,  # New Caledonia
    "VU": 548,  # Vanuatu
    "NZ": 554,  # New Zealand
    "NI": 558,  # Nicaragua
    "NE": 562,  # Niger
    "NG": 566,  # Nigeria
    "NU": 570,  # Niue
    "NF": 574,  # Norfolk Island
    "NO": 578,  # Norway
    "MP": 580,  # Northern Mariana Islands
    "UM": 581,  # United States Minor Outlying Islands
    "FM": 583,  # Micronesia, Federated States of
    "MH": 584,  # Marshall Islands
    "PW": 585,  # Palau
    "PK": 586,  # Pakistan
    "PA": 591,  # Panama
    "PG": 598,  # Papua New Guinea
    "PY": 600,  # Paraguay
    "PE": 604,  # Peru
    "PH": 608,  # Philippines
    "PN": 612,  # Pitcairn
    "PL": 616,  # Poland
    "PT": 620,  # Portugal
    "GW": 624,  # Guinea-Bissau
    "TL": 626,  # Timor-Leste
    "PR": 630,  # Puerto Rico
    "QA": 634,  # Qatar
    "RE": 638,  # Réunion
    "RO": 642,  # Romania
    "RU": 643,  # Russian Federation
    "RW": 646,  # Rwanda
    "BL": 652,  # Saint Barthélemy
    "SH": 654,  # Saint Helena, Ascension and Tristan da Cunha
    "KN": 659,  # Saint Kitts and Nevis
    "AI": 660,  # Anguilla
    "LC": 662,  # Saint Lucia
    "MF": 663,  # Saint Martin (French part)
    "PM": 666,  # Saint Pierre and Miquelon
    "VC": 670,  # Saint Vincent and the Grenadines
    "SM": 674,  # San Marino
    "ST": 678,  # Sao Tome and Principe
    "SA": 682,  # Saudi Arabia
    "SN": 686,  # Senegal
    "RS": 688,  # Serbia
    "SC": 690,  # Seychelles
    "SL": 694,  # Sierra Leone
    "SG": 702,  # Singapore
    "SK": 703,  # Slovakia
    "VN": 704,  # Viet Nam
    "SI": 705,  # Slovenia
    "SO": 706,  # Somalia
    "ZA": 710,  # South Africa
    "ZW": 716,  # Zimbabwe
    "ES": 724,  # Spain
    "SS": 728,  # South Sudan
    "SD": 729,  # Sudan
    "EH": 732,  # Western Sahara
    "SR": 740,  # Suriname
    "SJ": 744,  # Svalbard and Jan Mayen
    "SZ": 748,  # Swaziland
    "SE": 752,  # Sweden
    "CH": 756,  # Switzerland
    "SY": 760,  # Syrian Arab Republic
    "TJ": 762,  # Tajikistan
    "TH": 764,  # Thailand
    "TG": 768,  # Togo
    "TK": 772,  # Tokelau
    "TO": 776,  # Tonga
    "TT": 780,  # Trinidad and Tobago
    "AE": 784,  # United Arab Emirates
    "TN": 788,  # Tunisia
    "TR": 792,  # Turkey
    "TM": 795,  # Turkmenistan
    "TC": 796,  # Turks and Caicos Islands
    "TV": 798,  # Tuvalu
    "UG": 800,  # Uganda
    "UA": 804,  # Ukraine
    "MK": 807,  # Macedonia, the former Yugoslav Republic of
    "EG": 818,  # Egypt
    "GB": 826,  # United Kingdom
    "GG": 831,  # Guernsey
    "JE": 832,  # Jersey
    "IM": 833,  # Isle of Man
    "TZ": 834,  # Tanzania, United Republic of
    "US": 840,  # United States
    "VI": 850,  # Virgin Islands, U.S.
    "BF": 854,  # Burkina Faso
    "UY": 858,  # Uruguay
    "UZ": 860,  # Uzbekistan
    "VE": 862,  # Venezuela, Bolivarian Republic of
    "WF": 876,  # Wallis and Futuna
    "WS": 882,  # Samoa
    "YE": 887,  # Yemen
    "ZM": 894,  # Zambia
}

def get_country_id(country_code: str) -> Optional[int]:
    """
    Retrieves the Invoice Ninja country ID based on the 2-letter ISO country code.

    Args:
        country_code: The 2-letter ISO country code (e.g., "DE", "US").

    Returns:
        The corresponding integer country ID, or None if the code is not found.
    """
    country_id = COUNTRY_CODE_TO_ID_MAP.get(country_code.upper())
    if country_id is None:
        logger.warning(f"Could not find Invoice Ninja country ID for code: {country_code}")
    return country_id