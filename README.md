# Home Assistant - Octopus Energy France (custom)

Intégration Home Assistant pour remonter les infos principales d'un compte Octopus Energy France.

## Installation (manuel)
1. Copier le dossier `custom_components/octopus_energy_fr` dans `config/custom_components/`.
2. Redémarrer Home Assistant.
3. Aller dans **Paramètres > Appareils & Services > Ajouter une intégration**.
4. Chercher **Octopus Energy France**.

## Configuration
- **Clé API**: clé API Octopus (espace client)
- **ID compte**: identifiant de compte (ex: `A-12345678`)
- **Scan interval**: fréquence de rafraîchissement en minutes (5 à 1440)

## Entités créées
- Solde compte
- Dernière facture
- Électricité aujourd'hui (kWh)
- Gaz aujourd'hui (kWh)
- Prix électricité (€/kWh)

## Notes
Cette version est conçue pour être stable côté dev local et facilement publiable ensuite sur GitHub/HACS.
