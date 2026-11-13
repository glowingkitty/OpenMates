# Recherche d'entreprises (French company directory)

`business.company_ownership` reads French company data through the State's open-data [API Recherche d'entreprises](https://recherche-entreprises.api.gouv.fr/docs/) (DINUM, the data behind annuaire-entreprises.data.gouv.fr). It needs no key; the published limit is 7 requests per second.

Company lookups call `GET /search?q=<name or SIREN>` and use the matching result's identity (SIREN, name, legal form code, administrative status, head-office city) and `dirigeants`. Person lookups call `GET /search?nom_personne=<last>&prenoms_personne=<first>`, retrying once with the name order swapped, and list the companies where a director with that last name holds a position. France does not publish shareholders or the beneficial-owner register, so owners and holdings requests return directors with a warning instead.

Birth year and month (`annee_de_naissance`, `date_de_naissance`) and nationality are dropped. Each record links to the company page on annuaire-entreprises.data.gouv.fr.

Source: [API Recherche d'entreprises documentation](https://recherche-entreprises.api.gouv.fr/docs/).
