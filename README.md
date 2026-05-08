# Octopus Energy France — Intégration Home Assistant

<p align="center">
  <img src="custom_components/octopus_energy_fr/images/logo.svg" alt="Octopus Energy France" width="160"/>
</p>

<p align="center">
  <strong>Intégration non-officielle pour les clients Octopus Energy France</strong><br/>
  Suivi en temps réel de votre consommation électricité & gaz, tarifs, factures et charge intelligente véhicule électrique.
</p>

---

## ⚠️ Version minimale requise

> **Home Assistant 2024.4 ou supérieur est obligatoire.**
>
> Cette intégration utilise des APIs HA introduites en 2024 et ne fonctionnera **pas** sur une version antérieure.
> Les versions antérieures ne sont **pas** supportées et ne le seront jamais.
> **Mettez à jour Home Assistant avant d'installer cette intégration.**

---

## Fonctionnalités

- Authentification sécurisée via email/mot de passe (token JWT, rafraîchissement automatique)
- Support multi-compteurs (plusieurs PRMs électricité, plusieurs PCEs gaz)
- Données de consommation historiques (électricité : 365 j + mois précédent, gaz : 730 j)
- Détection automatique du type de tarif : **BASE** ou **Heures Pleines / Heures Creuses**
- Import des statistiques long-terme dans la base de données HA (graphiques Énergie)
- Solde de crédit, dernières factures électricité & gaz
- Charge intelligente véhicule électrique (Octopus Intelligent) : état, SOC cible, fenêtres de charge
- Options configurables : intervalle de mise à jour (5 – 1440 min, défaut 60 min)
- Reconnexion automatique (reauth flow) en cas d'expiration des identifiants

---

## Installation

### Via HACS (recommandé)

1. Dans HACS → **Intégrations** → menu ⋮ → **Dépôts personnalisés**
2. Ajouter `https://github.com/sethgrecko/octopus_energie` — catégorie **Integration**
3. Chercher **Octopus Energy France** → **Télécharger**
4. Redémarrer Home Assistant

### Manuellement

1. Copier le dossier `custom_components/octopus_energy_fr/` dans votre répertoire `config/custom_components/`
2. Redémarrer Home Assistant

---

## Configuration

1. **Paramètres** → **Appareils et services** → **+ Ajouter une intégration**
2. Rechercher **Octopus Energy France**
3. Entrer votre **adresse e-mail** et **mot de passe** du compte [Octopus Energy France](https://octopus.energy/fr/)
4. Si plusieurs comptes sont associés à votre e-mail, sélectionner le compte souhaité
5. (Optionnel) Modifier l'intervalle de mise à jour

### Options

Après installation, accéder aux options depuis la carte de l'intégration :

| Option | Par défaut | Plage |
|--------|-----------|-------|
| Intervalle de mise à jour | 60 min | 5 – 1440 min |

---

## Entités créées

### Électricité (par compteur PRM)

| Entité | Description | Unité |
|--------|-------------|-------|
| Type de contrat | BASE ou HP/HC | — |
| Puissance souscrite | Puissance contractuelle | kVA |
| Abonnement mensuel | Coût d'abonnement du mois en cours | € |
| Conso. mensuelle BASE | Consommation mensuelle (tarif BASE) | kWh |
| Conso. mensuelle HP | Consommation mensuelle Heures Pleines | kWh |
| Conso. mensuelle HC | Consommation mensuelle Heures Creuses | kWh |
| Coût mensuel BASE | Coût mensuel (tarif BASE) | € |
| Coût mensuel HP | Coût mensuel Heures Pleines | € |
| Coût mensuel HC | Coût mensuel Heures Creuses | € |
| Tarif BASE | Prix du kWh BASE | €/kWh |
| Tarif Heures Pleines | Prix du kWh HP | €/kWh |
| Tarif Heures Creuses | Prix du kWh HC | €/kWh |
| Dernier relevé | Valeur du dernier relevé journalier | kWh |
| Index BASE | Index Linky cumulé BASE | kWh |
| Index Heures Pleines | Index Linky cumulé HP | kWh |
| Index Heures Creuses | Index Linky cumulé HC | kWh |

### Gaz (par compteur PCE)

| Entité | Description | Unité |
|--------|-------------|-------|
| Conso. gaz mensuelle | Consommation mensuelle | kWh |
| Coût gaz mensuel | Coût mensuel | € |
| Statut contrat gaz | État du contrat | — |
| Abonnement gaz mensuel | Coût d'abonnement mensuel | € |
| Tarif gaz | Prix du kWh gaz | €/kWh |

### Compte

| Entité | Description | Unité |
|--------|-------------|-------|
| Crédit Octopus | Solde de crédit du compte | € |
| Dernière facture électricité | Montant de la dernière facture élec | € |
| Dernière facture gaz | Montant de la dernière facture gaz | € |

### Véhicule électrique (Octopus Intelligent — si activé)

| Entité | Type | Description |
|--------|------|-------------|
| État de charge véhicule | Sensor | Statut de charge actuel |
| En charge | Binary sensor | Vrai si charge en cours |
| SOC cible semaine | Number | Niveau de charge cible (semaine) |
| SOC cible week-end | Number | Niveau de charge cible (week-end) |
| Heure cible semaine | Sensor | Heure de charge cible (semaine) |
| Heure cible week-end | Sensor | Heure de charge cible (week-end) |
| Fenêtres de charge programmées | Sensor | Créneaux de charge planifiés |
| Charge boost | Switch | Activer/désactiver la charge boost |

---

## Appareils

L'intégration crée les appareils suivants dans le registre HA :

- **Compte Octopus Energy** — appareil parent logique
- **Linky `<PRM>`** — un appareil par compteur électricité (via Enedis)
- **Gazpar `<PCE>`** — un appareil par compteur gaz (via GrDF)
- **Véhicule électrique** — si Octopus Intelligent est actif sur le compte

---

## Statistiques long-terme

Les entités de consommation et de coût alimentent automatiquement le tableau de bord **Énergie** de Home Assistant.
Les données historiques sont importées depuis le premier démarrage (jusqu'à 365 jours pour l'électricité, 730 jours pour le gaz).

---

## Service

| Service | Description |
|---------|-------------|
| `octopus_energy_fr.force_update` | Force immédiatement la récupération des données |

---

## Dépannage

**Le flux de configuration ne se charge pas / "Invalid handler specified"**
→ Vérifier que Home Assistant est en version **2024.4 ou supérieure**.

**Erreur d'authentification**
→ Vérifier vos identifiants sur [octopus.energy/fr](https://octopus.energy/fr/). En cas d'expiration, l'intégration déclenche automatiquement un flux de reconnexion dans les notifications HA.

**Données manquantes**
→ Les données de consommation Enedis/GrDF peuvent avoir un délai de 24 à 48 h. Les capteurs afficheront `Indisponible` jusqu'à réception des premières données.

**Octopus Intelligent non détecté**
→ La fonctionnalité n'est activée que si votre compte dispose d'un véhicule électrique inscrit au programme Intelligent. Sans VE, les entités correspondantes ne sont pas créées.

---

## Confidentialité & sécurité

- Les identifiants sont stockés chiffrés dans la configuration HA (`config/.storage/`)
- Aucune donnée n'est envoyée vers des tiers — seule l'API Octopus Energy France est contactée
- Le token JWT est géré en mémoire avec rafraîchissement automatique avant expiration

---

## Contribuer

Les contributions sont les bienvenues ! Ouvrez une [issue](https://github.com/sethgrecko/octopus_energie/issues) ou une pull request.

---

## Licence

MIT — voir [LICENSE](LICENSE)

---

*Projet indépendant, non affilié à Octopus Energy Ltd.*
