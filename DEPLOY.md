# Put the app online and install it on your phone

## A. Upload to GitHub (no git needed)
1. Make a free account at github.com > New repository > name: ungal-vivasaayi > Public > Create.
2. Click "uploading an existing file". Drag the CONTENTS of this folder (app.py, requirements.txt, Procfile, static, esp32, README.md, DEPLOY.md).
   DO NOT upload a file named .env or farm.db (they contain your secret keys).
3. Commit changes.

## B. Host it free on Render
1. render.com > sign in with GitHub > New + > Web Service > choose your repo.
2. Language: Python 3. Build command: pip install -r requirements.txt
   Start command: gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120
   Instance type: Free.
3. Environment > add variables: GEMINI_API_KEY, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID (see README for Telegram).
4. Create Web Service. After a few minutes you get a link like https://ungal-vivasaayi.onrender.com
   The free server sleeps after 15 minutes without visitors. Open the link 1 minute before your demo.

## C. Make it a real Android app (APK)
1. Open pwabuilder.com in Chrome, paste your Render link, press Start.
2. Package for stores > Android > Generate package > download the zip.
3. Send the .apk from that zip to your phone, open it, allow "install unknown apps". 
   (Or simply open the link in phone Chrome > menu > Add to Home screen. Same app.)
4. On first open, allow Location, Microphone, Camera and Notifications.
