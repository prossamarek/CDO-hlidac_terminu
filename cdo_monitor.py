import os
import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import smtplib
from email.mime.text import MIMEText
from twilio.rest import Client

# ==========================================
# KONFIGURACE & NASTAVENÍ FILTRŮ
# ==========================================

URL_CALENDAR = "https://dcs.czechdance.org/calendar"
DB_FILE = "db.json"

# Načtení klíčů z prostředí (Environment Variables)
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")

TWILIO_SID = os.getenv("TWILIO_SID")
TWILIO_TOKEN = os.getenv("TWILIO_TOKEN")
TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_FROM")  # např. 'whatsapp:+14155238886'
WHATSAPP_TO = os.getenv("WHATSAPP_TO")                  # např. 'whatsapp:+420123456789'


def is_in_season(date_obj):
    """Rozpozná roční období na základě data soutěže."""
    month = date_obj.month
    if 9 <= month <= 12:
        return "AUTUMN"
    else:
        return "SPRING_SUMMER"


def filter_event(event):
    """
    Filtruje soutěže podle vaší přesné specifikace:
    - Podzim (Září-Prosinok): Jen Čechy, disciplíny HH, Art, DD, Disco Slow.
    - Jaro/Léto (Leden-Srpno): Pardubický, Královéhradecký kraj, MČech, MČR + Street, Art/Contemporary, DD.
    - Školení/Semináře: Celoročně.
    """
    title = event.get("title", "").lower()
    region = event.get("region", "").lower()
    disciplines = [d.lower() for d in event.get("disciplines", [])]
    event_date = event.get("event_date")

    # 1. Školení a vzdělávaní pro trenéry
    if "školení" in title or "seminář" in title or "trenér" in title:
        return True

    if not event_date:
        return True  # Pro jistotu nevylučovat, pokud datum chybí

    season = is_in_season(event_date)

    if season == "AUTUMN":
        # Podzimní liga: Pouze Čechy (vyloučit Moravu)
        is_cechy = "morava" not in region and "moravskoslezský" not in region and "olomoucký" not in region and "jihomoravský" not in region and "zlínský" not in region
        
        # Disciplíny: Hip Hop (HH), Art, Disco Dance (DD), Disco Slow
        allowed_disc = ["hip hop", "hh", "art", "disco dance", "dd", "disco slow"]
        has_discipline = any(d in " ".join(disciplines) or d in title for d in allowed_disc)
        
        return is_cechy and has_discipline

    else:
        # Jarní/Letní sezóna (Formace)
        is_target_region = any(r in region for r in ["pardubický", "královéhradecký", "čech", "česká republika", "mčr"])
        allowed_disc = ["street", "art", "contemporary", "disco dance", "dd"]
        has_discipline = any(d in " ".join(disciplines) or d in title for d in allowed_disc)

        return is_target_region and has_discipline


def send_notifications(subject, message):
    """Odešle e-mail i WhatsApp zprávu."""
    print(f"[NOTIFIKACE] {subject}\n{message}")

    # 1. Odeslání E-mailu
    if EMAIL_SENDER and EMAIL_PASSWORD and EMAIL_RECEIVER:
        try:
            msg = MIMEText(message, 'plain', 'utf-8')
            msg['Subject'] = subject
            msg['From'] = EMAIL_SENDER
            msg['To'] = EMAIL_RECEIVER

            with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
                server.login(EMAIL_SENDER, EMAIL_PASSWORD)
                server.sendmail(EMAIL_SENDER, EMAIL_RECEIVER, msg.as_string())
            print("-> E-mail úspěšně odeslán.")
        except Exception as e:
            print(f"-> Chyba při odesílání e-mailu: {e}")

    # 2. Odeslání WhatsAppu přes Twilio
    if TWILIO_SID and TWILIO_TOKEN and TWILIO_WHATSAPP_FROM and WHATSAPP_TO:
        try:
            client = Client(TWILIO_SID, TWILIO_TOKEN)
            client.messages.create(
                body=f"*{subject}*\n\n{message}",
                from_=TWILIO_WHATSAPP_FROM,
                to=WHATSAPP_TO
            )
            print("-> WhatsApp zpráva úspěšně odeslána.")
        except Exception as e:
            print(f"-> Chyba při odesílání WhatsAppu: {e}")


def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_db(db):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)


def parse_cdo_calendar():
    """Stáhne a načte data z kalendáře CDO."""
    response = requests.get(URL_CALENDAR)
    response.encoding = 'utf-8'
    soup = BeautifulSoup(response.text, 'html.parser')
    
    events = []
    # Zpracování HTML struktury (přizpůsobeno standardnímu layoutu CDO DCS)
    cards = soup.find_all('div', class_='event-card') or soup.find_all('tr', class_='event-row')

    for card in cards:
        try:
            # Extrakce dat z HTML prvků
            event_id = card.get('data-id') or card.find('a')['href'].split('/')[-1]
            title = card.find(class_='title').text.strip()
            
            # Získání dat
            raw_dates = card.find_all(class_='date')
            event_date_str = raw_dates[0].text.strip() if len(raw_dates) > 0 else None
            reg_open_str = card.find(class_='reg-open').text.strip() if card.find(class_='reg-open') else None
            reg_close_str = card.find(class_='reg-close').text.strip() if card.find(class_='reg-close') else None
            presence_close_str = card.find(class_='presence-close').text.strip() if card.find(class_='presence-close') else None

            # Převod na datetime objekty
            fmt = "%d.%m.%Y"
            event_date = datetime.strptime(event_date_str, fmt) if event_date_str else None
            reg_open = datetime.strptime(reg_open_str, fmt) if reg_open_str else None
            reg_close = datetime.strptime(reg_close_str, fmt) if reg_close_str else None
            presence_close = datetime.strptime(presence_close_str, fmt) if presence_close_str else None

            region = card.find(class_='region').text.strip() if card.find(class_='region') else ""
            disciplines = [d.text.strip() for d in card.find_all(class_='discipline')]

            events.append({
                "id": str(event_id),
                "title": title,
                "region": region,
                "disciplines": disciplines,
                "event_date": event_date,
                "deadlines": {
                    "reg_open": reg_open,
                    "reg_close": reg_close,
                    "presence_close": presence_close
                }
            })
        except Exception as e:
            continue

    return events


def check_deadlines():
    db = load_db()
    events = parse_cdo_calendar()
    today = datetime.now().date()

    for event in events:
        if not filter_event(event):
            continue  # Neodpovídá vašim filtrům, přeskočit

        event_id = event["id"]
        title = event["title"]
        deadlines = event["deadlines"]

        # Řetězcová reprezentace pro detekci ZMĚNY
        serialized_deadlines = {k: v.strftime("%Y-%m-%d") if v else None for k, v in deadlines.items()}

        # 1. KONTROLA ZMĚN (Detekce posunu termínu pořadatelem)
        if event_id in db:
            old_deadlines = db[event_id].get("serialized_deadlines", {})
            if old_deadlines != serialized_deadlines:
                msg = f"⚠️ DETEKOVÁNA ZMĚNA TERMÍNU!\nU akce '{title}' došlo k úpravě deadlinů na CDO:\n"
                for k, v in serialized_deadlines.items():
                    if v != old_deadlines.get(k):
                        msg += f"- {k}: z {old_deadlines.get(k)} na {v}\n"
                send_notifications(f"Změna termínu: {title}", msg)
        else:
            db[event_id] = {"notified": [], "serialized_deadlines": serialized_deadlines}

        db[event_id]["serialized_deadlines"] = serialized_deadlines

        # 2. KONTROLA ODPOČTŮ (7 dní, 3 dny, 1 den předem)
        deadline_names = {
            "reg_open": "Otevření registrace",
            "reg_close": "Uzavření registrace (DEADLINE)",
            "presence_close": "Uzavření prezence"
        }

        for dl_key, dl_date in deadlines.items():
            if not dl_date:
                continue

            days_left = (dl_date.date() - today).days
            dl_label = deadline_names[dl_key]

            # Dny, kdy chceme posílat varování
            target_days = [7, 3, 1]

            if days_left in target_days:
                notif_key = f"{dl_key}_{days_left}d"

                # Pokud jsme ještě tuto konkrétní notifikaci neodoslali
                if notif_key not in db[event_id]["notified"]:
                    subject = f"🚨 Upozornění: {title} - {dl_label} za {days_left} dny!"
                    body = (
                        f"Ahoj,\n\n"
                        f"Blíží se termín u soutěže: {title}\n"
                        f"📌 Milník: {dl_label}\n"
                        f"📅 Datum milníku: {dl_date.strftime('%d.%m.%Y')}\n"
                        f"⏳ Zbývá dní: {days_left}\n\n"
                        f"Odkaz na kalendář: {URL_CALENDAR}"
                    )
                    send_notifications(subject, body)
                    db[event_id]["notified"].append(notif_key)

    save_db(db)


if __name__ == "__main__":
    check_deadlines()
