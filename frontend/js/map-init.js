// Falcon-Pad — map-init.js
// Bootstrap: load airports, prefs, initial mission
// Copyright (C) 2024 Riesu — GNU GPL v3

loadAirports().then(() => {
  loadUiPrefs().then(() => {
    if(_missionCache) _redrawMission();
  });
});
