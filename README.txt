NAVIGATION ALERTS V2
=====================

Configuration déjà intégrée
----------------------------
Spots :
- Le Brusc — Six-Fours-les-Plages : 43.07639, 5.80375
- La Madrague — Giens : 43.04025, 6.11044

Règles :
- Vent : 12 à 40 nœuds
- Directions acceptées : E à SE (90° à 135°) et SO à NO (225° à 315°)
- Créneaux analysés : 08h à 20h
- Alertes : J-3 et J-1
- Contrôles automatiques : 07h et 17h, heure de Paris
- Une alerte de dégradation est envoyée si un créneau déjà détecté disparaît.

Météo :
- Open-Meteo, modèle Météo-France (AROME/ARPEGE)
- Données horaires : vent à 10 m, direction, rafales

Notifications :
- ntfy (application iOS/Android/web)
- Utilise un nom de topic privé et long, ou un topic protégé.

Mise en route locale
--------------------
1. Installer Python 3.11 ou plus récent.
2. Copier .env.example vers .env et choisir NTFY_TOPIC.
3. Définir les variables d'environnement de .env.
4. Lancer :
   python app.py
5. Ouvrir http://localhost:8080/check pour forcer un contrôle.

Avec Docker
-----------
docker build -t navigation-alerts-v2 .
docker run -d --restart unless-stopped \
  -p 8080:8080 \
  -e NTFY_TOPIC="ton-topic-prive" \
  navigation-alerts-v2

Important
---------
Pour recevoir des alertes lorsque ton ordinateur est éteint, cette application doit être
hébergée sur un serveur qui reste actif. Le code est prêt pour un hébergement Docker.
Le fichier state.json est créé automatiquement et sert à éviter les alertes répétitives.

Le Brusc et La Madrague sont ici configurés à partir des coordonnées du lieu/port.
Si ton point de mise à l'eau exact est différent, il suffit d'ajuster latitude/longitude
dans config.json.

Services utilisés :
- https://open-meteo.com/en/docs/meteofrance-api
- https://docs.ntfy.sh/
