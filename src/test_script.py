import time
import csv
import os
import json
from datetime import date, timedelta, datetime
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

# ==========================================
# 1. KONFIGURATION
# ==========================================

BASE_URL = "https://padel-wolfsburg.app.platzbuchung.de/public/booking/default/"
CSV_FILENAME = "auslastung_wolfsburg_full.csv"

# DEINE BUSINESS-DATEN
ANZAHL_COURTS = 3 

# PIXEL-LOGIK (Basierend auf deiner Messung)
# 104 Pixel entsprechen exakt 1 Stunde
PIXELS_PER_HOUR = 104.0 

# ÖFFNUNGSZEITEN (Für Kapazitäts-Berechnung)
# Dezimal: 21:30 Uhr = 21.5
WEEKEND_OPEN = 9.0
WEEKEND_CLOSE = 21.5
WEEKDAY_OPEN = 8.0
WEEKDAY_CLOSE = 22.5

# ==========================================
# 2. HELFER-FUNKTIONEN
# ==========================================

def get_target_date():
    """
    Gibt das Datum für die Analyse zurück.
    Wir nehmen HEUTE (date.today()), da wir das Skript abends laufen lassen
    und den aktuellen Tag erfassen wollen, bevor er vorbei ist.
    """
    return date.today().strftime("%Y-%m-%d")

def get_opening_hours_duration(check_date_str):
    """Berechnet die offenen Stunden basierend auf Wochentag/Wochenende"""
    d = datetime.strptime(check_date_str, "%Y-%m-%d")
    is_weekend = d.weekday() >= 5 # 5=Samstag, 6=Sonntag
    
    if is_weekend:
        return WEEKEND_CLOSE - WEEKEND_OPEN
    else:
        return WEEKDAY_CLOSE - WEEKDAY_OPEN

def setup_driver():
    """Startet den Chrome Browser"""
    chrome_options = Options()
    
    # --- WICHTIG FÜR GITHUB ACTIONS ---
    # Headless muss AKTIV sein (kein sichtbares Fenster)
    chrome_options.add_argument("--headless") 
    
    # Feste Fenstergröße ist wichtig für korrekte Pixel-Berechnung
    chrome_options.add_argument("--window-size=1920,1080")
    
    # Stabilitäts-Einstellungen für Server-Umgebungen
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--log-level=3") # Nur wichtige Fehler anzeigen
    
    # User-Agent (gibt sich als echter PC aus)
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36")
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    return driver

# ==========================================
# 3. HAUPT-LOGIK
# ==========================================

def main():
    driver = None
    try:
        # 1. Datum & URL setzen
        target_date = get_target_date()
        target_url = BASE_URL + target_date
        
        # 2. Theoretische Kapazität berechnen
        open_hours = get_opening_hours_duration(target_date)
        total_capacity_hours = open_hours * ANZAHL_COURTS
        
        print(f"--- Starte Analyse für: {target_date} ---")
        print(f"URL: {target_url}")
        
        # 3. Browser starten
        driver = setup_driver()
        driver.get(target_url)
        time.sleep(5) # Warten auf Seiten-Ladezeit

        # 4. Buchungen finden & analysieren
        # Wir suchen alle Elemente, die den Text "Belegt" enthalten
        all_booked_elements = driver.find_elements(By.XPATH, "//div[contains(text(), 'Belegt')]")
        
        total_booked_hours = 0.0
        booking_count = 0
        detailed_bookings_list = [] # Hier speichern wir Startzeit & Dauer jeder einzelnen Buchung
        
        for elem in all_booked_elements:
            # Nur sichtbare Elemente zählen (filtert unsichtbare Mobile-Ansichten)
            if elem.is_displayed():
                
                # A) DAUER über HÖHE berechnen
                h_px = float(elem.size['height'])
                hours = round(h_px / PIXELS_PER_HOUR, 2)
                # Auf 0.5 Schritte runden (z.B. 1.0, 1.5, 2.0)
                hours_snapped = round(hours * 2) / 2
                
                # B) START-ZEIT auslesen (aus dem HTML-Attribut 'start')
                start_attr = elem.get_attribute("start")
                start_time = float(start_attr) if start_attr else -1.0
                
                # C) END-ZEIT berechnen
                end_time = start_time + hours_snapped if start_time != -1.0 else -1.0

                # D) Daten sammeln
                total_booked_hours += hours_snapped
                booking_count += 1
                
                # Detail-Eintrag für diese spezifische Buchung
                booking_info = {
                    "start": start_time,
                    "end": end_time,
                    "duration": hours_snapped
                }
                detailed_bookings_list.append(booking_info)

        # 5. Auslastung berechnen
        # Cap bei 100% (falls durch Rahmen-Pixel leichte Überberechnung passiert)
        final_hours = min(total_booked_hours, total_capacity_hours)
        
        occupancy_rate = 0
        if total_capacity_hours > 0:
            occupancy_rate = round((final_hours / total_capacity_hours) * 100, 2)

        # Konsolen-Output (für Log-Files in GitHub Actions)
        print("-" * 30)
        print(f"Datum:             {target_date}")
        print(f"Buchungen (Anzahl): {booking_count}")
        print(f"Gebuchte Stunden:  {final_hours}")
        print(f"Kapazität:         {total_capacity_hours}")
        print(f"Auslastung:        {occupancy_rate}%")
        print("-" * 30)

        # 6. Speichern in CSV
        file_exists = os.path.isfile(CSV_FILENAME)
        weekday_name = datetime.strptime(target_date, "%Y-%m-%d").strftime("%A")
        
        # Wir speichern die Liste der Buchungen als JSON-String in einer Spalte
        # Das sieht dann so aus: "[{'start': 10.0, 'end': 11.0, 'duration': 1.0}, ...]"
        details_json = json.dumps(detailed_bookings_list)

        with open(CSV_FILENAME, mode='a', newline='', encoding='utf-8') as file:
            writer = csv.writer(file, delimiter=';')
            
            # Header schreiben (nur wenn Datei neu ist)
            if not file_exists:
                writer.writerow([
                    "Datum", 
                    "Wochentag", 
                    "Kapazitaet_Std", 
                    "Gebucht_Std", 
                    "Auslastung_Prozent", 
                    "Anzahl_Buchungen", 
                    "Details_JSON" # <--- Hier stehen die genauen Zeiten drin
                ])
            
            # Zeile schreiben
            writer.writerow([
                target_date, 
                weekday_name, 
                total_capacity_hours, 
                final_hours, 
                occupancy_rate, 
                booking_count, 
                details_json
            ])
            print(f"Daten erfolgreich in '{CSV_FILENAME}' gespeichert.")

    except Exception as e:
        print(f"KRITISCHER FEHLER: {e}")
        # Wichtig für GitHub Actions: Fehler melden, damit der Workflow als 'Failed' markiert wird
        exit(1) 

    finally:
        if driver:
            driver.quit()

if __name__ == "__main__":
    main()