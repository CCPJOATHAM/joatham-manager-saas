# Couverture des devises et retour après taux indisponible

## Inventaire réel

La liste ci-dessous provient de `core.services.world.get_currency_choices()`, utilisée par l'inscription et le profil : **142 codes distincts**, trois lettres, tous présents dans `CURRENCY_DETAILS`. Elle ne se limite pas aux francs : EUR, GBP, CHF, JPY, CNY, CAD, AUD, KWD, ZAR et les autres codes passent par le même chemin de conversion.

Un contrôle en lecture seule de [l'API publique USD](https://open.er-api.com/v6/latest/USD) a trouvé **141 taux positifs et finis** parmi ces codes. Date de mise à jour annoncée par le fournisseur : `Fri, 20 Nov 2026 00:02:32 +0000`. Code absent : **KPW**. Cette disponibilité est un constat daté, pas une garantie permanente. La [documentation du fournisseur](https://www.exchangerate-api.com/docs/supported-currencies) précise les devises proposées ; les taux numériques réels ne sont pas redistribués dans le dépôt.

Une devise offerte par JOATHAM reste offerte même si le fournisseur n'a pas de taux. Un taux manuel actif peut la rendre convertible. USD vers USD utilise toujours le taux d'identité 1, même hors ligne. Les anciens libellés FC/FCFA restent des alias historiques ; XAF et XOF restent distincts. Aucun code de la liste n'est remplacé ou retiré par ce chantier, et aucun taux n'est inventé.

## Affichage et changements successifs

- Montant, taux et devise doivent être cohérents et valides pour afficher une estimation. Les valeurs absentes, non finies, négatives, les taux nuls et les données d'une ancienne devise donnent l'état traduit « Conversion temporairement indisponible. », sans None, NaN, montant précédent ou faux zéro. Le prix de référence USD reste visible.
- L'état est recalculé à chaque sélection ; le retour à une devise avec un taux valide réaffiche immédiatement montant et taux. Une absence de taux n'est pas mémorisée comme un échec global. Un nouveau taux manuel est utilisable dès l'estimation suivante.
- Les prix USD et la réduction annuelle de **20 %** ne changent pas. Les estimations conservent la précision de stockage actuelle de l'application, deux décimales pour les montants et huit pour les taux.
- Une réponse du fournisseur annonçant une autre devise de base est rejetée pour ne pas multiplier le prix USD par un taux d'une autre base.

## Tests

- Inventaire synchronisé avec les 142 choix réels.
- Lecture d'une réponse fournisseur contenant un taux de test pour chacun des 142 codes.
- Conversion réelle du service, sur base de test, pour tous les codes en FR/EN, mensuel et annuel ; taux synthétiques déterministes, sans réseau ni changement de tarification.
- Absence de taux pour tous les codes : état indisponible, sauf USD vers USD ; taux manuel KPW apparaissant après un échec immédiatement réutilisé.
- Parcours HTTP réel de modification du profil puis consultation des trois pages d'abonnement, dans les deux langues : EUR → KPW indisponible → CAD → EUR → JPY → KPW indisponible → JPY → GBP → CHF → CNY → KWD → ZAR → USD. Les retours à une devise disponible réutilisent le taux enregistré sans appeler le fournisseur.
- Tests Node de l'affichage pour tous les codes en FR/EN, champs invalides, données d'une autre devise et retour après indisponibilité ; prix USD mensuel/annuel conservés.
- Contrôles navigateur sur les templates et scripts réels, avec données fictives et taux simulés. Les tests de base sont exécutés en CI PostgreSQL, Docker local étant indisponible. Aucun accès au VPS et aucune donnée de production consultée.

## Captures des états et du retour à une devise disponible

Les taux des captures sont des fixtures de test, pas les taux réels du fournisseur.

| État | Français, ordinateur | Anglais, mobile |
|---|---|---|
| EUR disponible | [Voir](previews/all-currencies/conversion-EUR-fr-desktop.png) | [Voir](previews/all-currencies/conversion-EUR-en-mobile.png) |
| KPW indisponible | [Voir](previews/all-currencies/conversion-KPW-fr-desktop.png) | [Voir](previews/all-currencies/conversion-KPW-en-mobile.png) |
| Retour à JPY disponible | [Voir](previews/all-currencies/conversion-JPY-fr-desktop.png) | [Voir](previews/all-currencies/conversion-JPY-en-mobile.png) |

## Liste des codes

| Code | Libellé du projet | Taux dans la réponse publique contrôlée |
|---|---|---|
| AED | Dirham des Emirats arabes unis | Disponible |
| AFN | Afghani | Disponible |
| ALL | Lek albanais | Disponible |
| AMD | Dram armenien | Disponible |
| AOA | Kwanza angolais | Disponible |
| ARS | Peso argentin | Disponible |
| AUD | Dollar australien | Disponible |
| AZN | Manat azerbaidjanais | Disponible |
| BAM | Mark convertible | Disponible |
| BBD | Dollar barbadien | Disponible |
| BDT | Taka bangladais | Disponible |
| BGN | Lev bulgare | Disponible |
| BHD | Dinar bahreini | Disponible |
| BIF | Franc burundais | Disponible |
| BND | Dollar brunien | Disponible |
| BOB | Boliviano | Disponible |
| BRL | Real bresilien | Disponible |
| BSD | Dollar bahamien | Disponible |
| BTN | Ngultrum | Disponible |
| BWP | Pula | Disponible |
| BYN | Rouble bielorusse | Disponible |
| BZD | Dollar belizien | Disponible |
| CAD | Dollar canadien | Disponible |
| CDF | Franc congolais | Disponible |
| CHF | Franc suisse | Disponible |
| CLP | Peso chilien | Disponible |
| CNY | Yuan chinois | Disponible |
| COP | Peso colombien | Disponible |
| CRC | Colon costaricien | Disponible |
| CUP | Peso cubain | Disponible |
| CVE | Escudo cap-verdien | Disponible |
| CZK | Couronne tcheque | Disponible |
| DJF | Franc djiboutien | Disponible |
| DKK | Couronne danoise | Disponible |
| DZD | Dinar algerien | Disponible |
| EGP | Livre egyptienne | Disponible |
| ERN | Nakfa | Disponible |
| ETB | Birr ethiopien | Disponible |
| EUR | Euro | Disponible |
| FJD | Dollar fidjien | Disponible |
| GBP | Livre sterling | Disponible |
| GEL | Lari georgien | Disponible |
| GHS | Cedi ghanéen | Disponible |
| GMD | Dalasi gambien | Disponible |
| GNF | Franc guineen | Disponible |
| GTQ | Quetzal | Disponible |
| GYD | Dollar guyanien | Disponible |
| HNL | Lempira | Disponible |
| HTG | Gourde haitienne | Disponible |
| HUF | Forint | Disponible |
| IDR | Roupie indonesienne | Disponible |
| ILS | Shekel israélien | Disponible |
| INR | Roupie indienne | Disponible |
| IQD | Dinar irakien | Disponible |
| IRR | Rial iranien | Disponible |
| ISK | Couronne islandaise | Disponible |
| JMD | Dollar jamaicain | Disponible |
| JOD | Dinar jordanien | Disponible |
| JPY | Yen japonais | Disponible |
| KES | Shilling kenyan | Disponible |
| KGS | Som kirghize | Disponible |
| KHR | Riel cambodgien | Disponible |
| KMF | Franc comorien | Disponible |
| KPW | Won nord-coreen | Absent — taux manuel possible |
| KRW | Won sud-coreen | Disponible |
| KWD | Dinar koweitien | Disponible |
| KZT | Tenge kazakh | Disponible |
| LAK | Kip lao | Disponible |
| LBP | Livre libanaise | Disponible |
| LKR | Roupie sri-lankaise | Disponible |
| LRD | Dollar liberien | Disponible |
| LSL | Loti | Disponible |
| LYD | Dinar libyen | Disponible |
| MAD | Dirham marocain | Disponible |
| MDL | Leu moldave | Disponible |
| MGA | Ariary | Disponible |
| MKD | Denar macedonien | Disponible |
| MMK | Kyat | Disponible |
| MNT | Tugrik | Disponible |
| MRU | Ouguiya | Disponible |
| MUR | Roupie mauricienne | Disponible |
| MVR | Rufiyaa | Disponible |
| MWK | Kwacha malawite | Disponible |
| MXN | Peso mexicain | Disponible |
| MYR | Ringgit malaisien | Disponible |
| MZN | Metical mozambicain | Disponible |
| NAD | Dollar namibien | Disponible |
| NGN | Naira | Disponible |
| NIO | Cordoba | Disponible |
| NOK | Couronne norvegienne | Disponible |
| NPR | Roupie nepalaise | Disponible |
| NZD | Dollar neo-zelandais | Disponible |
| OMR | Rial omanais | Disponible |
| PAB | Balboa | Disponible |
| PEN | Sol | Disponible |
| PGK | Kina | Disponible |
| PHP | Peso philippin | Disponible |
| PKR | Roupie pakistanaise | Disponible |
| PLN | Zloty | Disponible |
| PYG | Guarani | Disponible |
| QAR | Riyal qatari | Disponible |
| RON | Leu roumain | Disponible |
| RSD | Dinar serbe | Disponible |
| RUB | Rouble russe | Disponible |
| RWF | Franc rwandais | Disponible |
| SAR | Riyal saoudien | Disponible |
| SBD | Dollar des Salomon | Disponible |
| SCR | Roupie seychelloise | Disponible |
| SDG | Livre soudanaise | Disponible |
| SEK | Couronne suedoise | Disponible |
| SGD | Dollar de Singapour | Disponible |
| SLE | Leone | Disponible |
| SOS | Shilling somalien | Disponible |
| SRD | Dollar surinamais | Disponible |
| SSP | Livre sud-soudanaise | Disponible |
| STN | Dobra | Disponible |
| SYP | Livre syrienne | Disponible |
| SZL | Lilangeni | Disponible |
| THB | Baht | Disponible |
| TJS | Somoni | Disponible |
| TMT | Manat turkmene | Disponible |
| TND | Dinar tunisien | Disponible |
| TOP | Paanga | Disponible |
| TRY | Livre turque | Disponible |
| TTD | Dollar de Trinite-et-Tobago | Disponible |
| TZS | Shilling tanzanien | Disponible |
| UAH | Hryvnia | Disponible |
| UGX | Shilling ougandais | Disponible |
| USD | Dollar americain | Disponible |
| UYU | Peso uruguayen | Disponible |
| UZS | Soum ouzbek | Disponible |
| VES | Bolivar | Disponible |
| VND | Dong | Disponible |
| VUV | Vatu | Disponible |
| WST | Tala | Disponible |
| XAF | Franc CFA | Disponible |
| XCD | Dollar des Caraibes orientales | Disponible |
| XOF | Franc CFA BCEAO | Disponible |
| YER | Rial yemenite | Disponible |
| ZAR | Rand | Disponible |
| ZMW | Kwacha zambien | Disponible |
| ZWG | Zimbabwe Gold | Disponible |
