# உங்கள் விவசாயி (Ungal Vivasaayi)
AI farm advisor for delta paddy farmers. Real data: Open-Meteo weather + modelled soil moisture, GDACS cyclone feed,
Gemini (Tamil advice, voice questions, instant leaf diagnosis), Telegram phone alerts, ESP32 sensors and pump.

## Run (Windows)
1. Install Python 3.10+ (tick "Add to PATH").
2. Open terminal in this folder (where app.py is):
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   python app.py
3. Open http://localhost:5000 in Chrome. Paste your free Gemini key (aistudio.google.com/apikey) in the green box.

## Phone alerts (Telegram, free)
1. In Telegram search @BotFather, send /newbot, follow steps, copy the token.
2. Open your new bot and send "hi".
3. App > பண்ணை tab > paste token > சேமி. A message arrives on your phone. Storm/heavy-rain alerts are sent automatically every 30 minutes check.

## Use on phone
Run `ngrok http 5000`, open the https link on your phone in Chrome. Mic and notifications need https. Menu > Add to Home screen.

## Demo mode
பண்ணை tab > tick DEMO. Shows a storm scenario, sends a [DEMO] Telegram alert. Say clearly it is a demo.

## Hardware (optional)
See esp32_ungal_vivasaayi.ino. Once sensors send data, soil moisture switches from "கணிப்பு" (modelled) to "சென்சார்".
