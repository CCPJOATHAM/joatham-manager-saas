# Règles JOATHAM Manager

Toute page, fonctionnalité ou modification d'interface livrée doit être disponible en français et en anglais.

- Marquer les textes des templates avec les balises Django i18n. Utiliser blocktranslate et ses pluriels pour les phrases contenant des variables ou des compteurs.
- Utiliser gettext_lazy pour les libellés définis à l'import et gettext pour les textes calculés pendant une requête. Utiliser des paramètres nommés pour les valeurs dynamiques.
- Inclure les formulaires, validations, notifications, emails, titres, attributs accessibles, états vides, exports et PDF.
- Traduire les textes JavaScript via le catalogue djangojs et le gettext de Django. Respecter la langue active pour les dates et les nombres.
- Conserver les noms d'entreprises, noms de personnes, descriptions et contenus saisis dans leur langue d'origine. Conserver les codes techniques des statuts, rôles et interfaces externes.
- Mettre à jour et compiler les catalogues fr/en des domaines django et djangojs dans chaque PR concernée. Les entrées utilisées doivent avoir une traduction anglaise relue et aucune entrée fuzzy utilisée.
- Ajouter ou adapter les tests des parcours modifiés en français et en anglais, y compris la conservation des données saisies. Vérifier la persistance de langue si le parcours touche l'authentification ou le profil.
- Exécuter le contrôle des catalogues et les tests bilingues avant de demander une revue. Décrire les contrôles FR/EN dans la PR.
- Les workflows de contrôle de PR n'effectuent aucune mise en production.
- Pour un nouvel événement système visible, ajouter ses libellés et son modèle de description dans core/audit_i18n.py ; vérifier le rendu FR/EN des événements historiques et préserver les notes libres et données persistées.
- Pour les journaux d'activité persistés, ajouter les intitulés et modèles de description au registre core/audit_i18n.py et vérifier l'affichage dans les deux langues ; conserver les descriptions stockées et les valeurs saisies.
